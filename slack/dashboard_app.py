"""Open the dashboard from the unused fourth position in the stats toolbar."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import BoundedSemaphore
from uuid import uuid4
from zoneinfo import ZoneInfo

from database.dashboard_db import load_dashboard_data
from slack.dashboard_report import build_dashboard_report
from slack.stats_report_server import REPORT_TTL_SECONDS, report_url

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='dashboard')
SLOTS = BoundedSemaphore(4)
logger = logging.getLogger(__name__)


def dashboard_view(text, url=None):
    blocks = [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}}]
    if url:
        blocks.append({'type': 'actions', 'elements': [{
            'type': 'button', 'action_id': 'dashboard_link',
            'text': {'type': 'plain_text', 'text': '통계 대시보드 열기'}, 'url': url}]})
    return {'type': 'modal', 'title': {'type': 'plain_text', 'text': 'WAHIS 통계 대시보드'},
            'close': {'type': 'plain_text', 'text': '닫기'}, 'blocks': blocks}


def dashboard_selection(values):
    selected = {}
    for field in ('disease', 'region', 'country'):
        option = values.get(f'stats_{field}_block', {}).get(
            f'stats_{field}_select', {}).get('selected_option') or {}
        selected[field] = option.get('value', '')
    for field in ('start', 'end'):
        raw = (values.get(f'stats_{field}_text_block', {}).get(
            f'stats_{field}_text', {}).get('value') or '').strip()
        raw = raw or values.get(f'stats_{field}_date_block', {}).get(
            f'stats_{field}_date', {}).get('selected_date')
        if raw:
            parsed = datetime.strptime(raw, '%Y%m%d' if len(raw) == 8 else '%Y-%m-%d')
            selected[field] = parsed.date().isoformat()
    if selected.get('start') and selected.get('end') and selected['start'] > selected['end']:
        raise ValueError('시작일은 종료일보다 늦을 수 없습니다.')
    return selected


def register_dashboard_handlers(app, reports):
    @app.action('dashboard_link')
    def acknowledge(ack):
        ack()

    @app.action('dashboard_open')
    def open_dashboard(ack, body, client):
        ack()
        try:
            initial = dashboard_selection(body['view'].get('state', {}).get('values', {}))
        except ValueError:
            client.views_push(trigger_id=body['trigger_id'], view=dashboard_view(
                '날짜를 YYYYMMDD 또는 YYYY-MM-DD 형식으로 입력하고 시작일·종료일을 확인해주세요.'))
            return
        if not SLOTS.acquire(blocking=False):
            client.views_push(trigger_id=body['trigger_id'], view=dashboard_view(
                '다른 대시보드를 생성 중입니다. 잠시 후 다시 시도해주세요.'))
            return
        try:
            result = client.views_push(trigger_id=body['trigger_id'], view=dashboard_view(
                '기간별 추세와 전년 동기 비교를 준비하고 있습니다.'))
            view_id = result['view']['id']
        except Exception:
            SLOTS.release()
            raise

        def work():
            try:
                key = uuid4().hex
                url = report_url(key)
                if not url:
                    raise ValueError('Railway 공개 도메인 또는 STATS_REPORT_BASE_URL을 설정해주세요.')
                today = datetime.now(ZoneInfo('Asia/Seoul')).date()
                data = load_dashboard_data(today)
                reports[key] = {'html': build_dashboard_report(data, today, initial),
                                'expires_at': time.time() + REPORT_TTL_SECONDS}
                while len(reports) > 30:
                    reports.pop(next(iter(reports)), None)
                view = dashboard_view('대시보드가 준비됐습니다. 브라우저에서 필터와 그래프를 '
                                      '직접 조절할 수 있습니다.\n발생일 기준 고유 outbreak 집계 · '
                                      '조회 시점 데이터 · 링크 유효기간 1시간', url)
            except Exception as error:
                logger.warning('Dashboard generation failed: %s', type(error).__name__)
                view = dashboard_view(str(error) if isinstance(error, ValueError) else
                                      '대시보드를 만들지 못했습니다. DB 연결과 서버 로그를 확인해주세요.')
            finally:
                SLOTS.release()
            try:
                client.views_update(view_id=view_id, view=view)
            except Exception as error:
                logger.warning('Dashboard modal update failed: %s', type(error).__name__)
        try:
            POOL.submit(work)
        except Exception:
            SLOTS.release()
            raise
