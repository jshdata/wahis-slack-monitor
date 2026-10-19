"""Private Slack search for file-backed WAHIS control-measure snapshots."""
from datetime import date
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from wahis import control_storage

logger = logging.getLogger(__name__)
POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='control-measures')
SLOTS = BoundedSemaphore(4)


def text(value):
    return str(value or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def section(value):
    return {'type': 'section', 'text': {'type': 'mrkdwn', 'text': value[:2900]}}


def modal(blocks):
    return {'type': 'modal', 'callback_id': 'control_results',
            'title': {'type': 'plain_text', 'text': '방역 조치 조회'},
            'close': {'type': 'plain_text', 'text': '닫기'}, 'blocks': blocks}


def settings(filters=None):
    filters = filters or {}
    view = modal([section('국가·질병·반기별로 보고된 방역 조치를 조회합니다. '
                          '시행 횟수·접종 마릿수·접종률을 뜻하지 않습니다.\n'
                          '국가는 영문 이름의 일부로 검색할 수 있습니다. 예: Korea, Japan')])
    view['callback_id'] = 'control_settings'
    view['submit'] = {'type': 'plain_text', 'text': '조회하기'}
    for name, label, choices, default in (
        ('disease', '질병', [(c, c) for c in control_storage.CODES], 'HPAI'),
        ('year', '연도', [('all', '전체'), *[(str(y), str(y)) for y in range(date.today().year, 2004, -1)]], 'all'),
        ('semester', '반기', [('all', '전체'), ('1', '상반기'), ('2', '하반기')], 'all'),
        ('scope', '방역 조치 범위', [('all', '모든 방역 조치'), ('vaccination', '예방접종 관련 (시행·금지)'),
                                    ('official', '공식 예방접종만')], 'all')):
        options = [{'text': {'type': 'plain_text', 'text': title}, 'value': val} for val, title in choices]
        selected = next((o for o in options if o['value'] == filters.get(name, default)), options[0])
        view['blocks'].append({'type': 'input', 'block_id': name,
            'label': {'type': 'plain_text', 'text': label},
            'element': {'type': 'static_select', 'action_id': 'value', 'options': options,
                        'initial_option': selected}})
    country = {'type': 'plain_text_input', 'action_id': 'value', 'max_length': 200,
               'placeholder': {'type': 'plain_text', 'text': '비워두면 전체 국가'}}
    if filters.get('country'):
        country['initial_value'] = filters['country']
    view['blocks'].append({'type': 'input', 'block_id': 'country', 'optional': True,
                           'label': {'type': 'plain_text', 'text': '국가 (영문 부분 검색)'}, 'element': country})
    return view


def result_view(filters, page=0):
    result = control_storage.query(filters, page)
    page, count = result['page'], result['total']
    last = max(1, (count + control_storage.PAGE_SIZE - 1) // control_storage.PAGE_SIZE)
    year = filters.get('year', 'all')
    year_label = '전체 연도' if year == 'all' else year
    semester_label = {'1': '상반기', '2': '하반기'}.get(filters.get('semester'), '전체 반기')
    scope_label = {'vaccination': '접종 시행·금지', 'official': '공식 예방접종만'}.get(filters.get('scope'), '모든 방역 조치')
    blocks = [section(f'*{text(filters["disease"])} · {text(year_label)} · '
                      f'{text(filters.get("country") or "전체 국가")}*\n'
                      f'{semester_label} · {scope_label}\n'
                      f'보고 항목 {count:,}건 · {page + 1}/{last} 페이지'),
              section(f'자료 수집 완료: {text(result["snapshot_at"])}\n'
                      '보고된 조치 항목이며 실제 시행 횟수나 접종 마릿수가 아닙니다. '
                      'HPAI는 가금·가금 외 보고를 구분해 표시합니다.')]
    if not count:
        blocks.append(section('해당 조건의 보고 항목이 없습니다. 조치 미시행을 뜻하지 않습니다.'))
    for row in result['rows']:
        blocks.append(section(f'*{text(row["country"])} · {text(row["semester"])}*\n'
                              f'{text(row["disease"])}\n'
                              f'{text(row["region"])} · {text(row["category"])} · {text(row["species"])}\n'
                              f'*{text(row["measure"])}*'))
    buttons = []
    for label, target in [('이전', page - 1), ('다음', page + 1)]:
        if 0 <= target < last and target != page:
            buttons.append({'type': 'button', 'action_id': 'control_page',
                            'text': {'type': 'plain_text', 'text': label},
                            'value': json.dumps({'filters': filters, 'page': target})})
    buttons.append({'type': 'button', 'action_id': 'control_back',
                    'text': {'type': 'plain_text', 'text': '조건 변경'}, 'value': json.dumps(filters)})
    blocks.append({'type': 'actions', 'elements': buttons})
    return modal(blocks)


def submit(client, view_id, task):
    if not SLOTS.acquire(blocking=False):
        client.views_update(view_id=view_id, view=modal([section('다른 조회를 처리 중입니다. 잠시 후 다시 시도해주세요.')]))
        return
    def work():
        try:
            try:
                view = task()
            except Exception as error:
                logger.warning('Control measures query failed: %s', type(error).__name__)
                view = modal([section('방역 조치를 불러오지 못했습니다. 잠시 후 다시 조회해 주세요.')])
            try:
                client.views_update(view_id=view_id, view=view)
            except Exception as error:
                response = getattr(error, 'response', {})
                logger.warning('Control measures view failed: %s error=%s details=%s', type(error).__name__,
                               response.get('error'), response.get('response_metadata'))
                client.views_update(view_id=view_id, view=modal([section('조회 화면을 표시하지 못했습니다. 창을 닫고 다시 조회해 주세요.')]))
        finally:
            SLOTS.release()
    try:
        POOL.submit(work)
    except Exception:
        SLOTS.release()
        raise


def register_control_handlers(app):
    @app.action('control_measures_open')
    def open_settings(ack, body, client):
        ack()
        client.views_push(trigger_id=body['trigger_id'], view=settings())

    @app.view('control_settings')
    def search(ack, body, view, client):
        values = view['state']['values']
        filters = {name: values[name]['value']['selected_option']['value']
                   for name in ('disease', 'year', 'semester', 'scope')}
        filters['country'] = (values.get('country', {}).get('value', {}).get('value') or '').strip()
        ack(response_action='update', view=modal([section('방역 조치를 조회하고 있습니다.')]))
        submit(client, view['id'], lambda: result_view(filters))

    @app.action('control_page')
    def page(ack, body, client):
        ack()
        data = json.loads(body['actions'][0]['value'])
        submit(client, body['view']['id'], lambda: result_view(data['filters'], data['page']))

    @app.action('control_back')
    def back(ack, body, client):
        ack()
        client.views_update(view_id=body['view']['id'], view=settings(json.loads(body['actions'][0]['value'])))
