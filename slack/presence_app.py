"""Slack settings and private HTML links for occurrence presence tables."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import BoundedSemaphore
from uuid import uuid4
from zoneinfo import ZoneInfo

from database.presence_db import disease_codes, load_presence_data
from slack.presence_report import build_presence_report
from slack.stats_report_server import REPORT_TTL_SECONDS, report_url
from slack.multi_filters import multi_element, selected_value
from database.filters import selection_values

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='presence')
SLOTS = BoundedSemaphore(4)
logger = logging.getLogger(__name__)


def message_view(text, url=None):
    blocks = [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}}]
    if url:
        blocks.append({'type': 'actions', 'elements': [{
            'type': 'button', 'action_id': 'presence_report_link',
            'text': {'type': 'plain_text', 'text': '발생 여부 표 열기'}, 'url': url}]})
    return {'type': 'modal', 'title': {'type': 'plain_text', 'text': '질병별 발생 여부 표'},
            'close': {'type': 'plain_text', 'text': '닫기'}, 'blocks': blocks}


def settings_view(disease='HPAI'):
    choices = [('all', '모든 질병'), ('HPAI', 'HPAI (가금·가금 외)'),
               ('ASF', 'ASF'), ('FMD', 'FMD'), ('LSD', 'LSD'), ('BSE', 'BSE')]
    options = [{'text': {'type': 'plain_text', 'text': label}, 'value': value}
               for value, label in choices]
    modes = [{'text': {'type': 'plain_text', 'text': label}, 'value': value}
             for value, label in [('year', '연도별'), ('month', '월별'), ('both', '연도별 + 월별')]]
    view = message_view('전체 기간 · 모든 권역·국가를 표시합니다.\n'
                        'O: 해당 기간 발생 기록 있음 · 공백: 기록 없음\n'
                        'HPAI는 가금과 가금 외를 별도 표로 표시합니다.')
    view.update(callback_id='presence_settings', submit={'type': 'plain_text', 'text': '표 만들기'})
    for block_id, label, values, initial in [
            ('presence_disease', '질병', options, (selection_values(disease) or ['all'])[0]),
            ('presence_mode', '표시 단위', modes, 'year')]:
        view['blocks'].append({'type': 'input', 'block_id': block_id,
            'label': {'type': 'plain_text', 'text': label},
            'element': {'type': 'static_select', 'action_id': 'select', 'options': values,
                        'initial_option': next(o for o in values if o['value'] == initial)}})
    disease_element = view['blocks'][1]['element']
    view['blocks'][1]['element'] = multi_element(disease_element)
    view['blocks'][1]['element']['initial_options'] = [
        option for option in options if option['value'] in selection_values(disease)]
    if not view['blocks'][1]['element']['initial_options']:
        view['blocks'][1]['element'].pop('initial_options')
    view['blocks'][1]['optional'] = True
    return view


def register_presence_handlers(app, reports):
    @app.action('presence_open')
    def open_settings(ack, body, client):
        ack()
        values = body['view'].get('state', {}).get('values', {})
        disease = selected_value(values.get('stats_disease_block', {}).get('stats_disease_select', {}))
        client.views_push(trigger_id=body['trigger_id'], view=settings_view(disease))

    @app.action('presence_report_link')
    def acknowledge_link(ack):
        ack()

    @app.view('presence_settings')
    def generate(ack, body, view, client):
        values = view['state']['values']
        disease = selected_value(values['presence_disease']['select'])
        mode = values['presence_mode']['select']['selected_option']['value']
        try:
            disease_codes(disease)
            if mode not in ('year', 'month', 'both'):
                raise ValueError('지원하지 않는 표시 단위입니다.')
        except ValueError as error:
            ack(response_action='errors', errors={'presence_disease': str(error)})
            return
        if not SLOTS.acquire(blocking=False):
            ack(response_action='errors', errors={'presence_mode': '다른 표를 처리 중입니다. 잠시 후 다시 시도해주세요.'})
            return
        ack(response_action='update', view=message_view('발생 여부 표를 만들고 있습니다.'))
        view_id = body['view']['id']

        def work():
            try:
                key = uuid4().hex
                url = report_url(key)
                if not url:
                    raise ValueError('Railway 공개 도메인 또는 STATS_REPORT_BASE_URL을 설정해주세요.')
                countries, facts = load_presence_data(disease)
                today = datetime.now(ZoneInfo('Asia/Seoul')).date()
                reports[key] = {'html': build_presence_report(countries, facts, mode, today),
                                'expires_at': time.time() + REPORT_TTL_SECONDS}
                while len(reports) > 30:
                    reports.pop(next(iter(reports)), None)
                result = message_view('표가 준비됐습니다. 아래 버튼으로 브라우저에서 열어보세요.\n'
                                      '날짜별 O 합계와 총 O 합계는 표 마지막 행에 표시됩니다. 링크는 1시간 동안 유효합니다.', url)
            except Exception as error:
                logger.warning('Presence report failed: %s', type(error).__name__)
                result = message_view(str(error) if isinstance(error, ValueError) else
                                      '표 생성에 실패했습니다. DB 연결 및 서버 로그를 확인해주세요.')
            finally:
                SLOTS.release()
            try:
                client.views_update(view_id=view_id, view=result)
            except Exception as error:
                logger.warning('Presence modal update failed: %s', type(error).__name__)
        POOL.submit(work)
