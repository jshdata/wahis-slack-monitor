"""WOAH document modal. All responses stay in the requesting user's modal."""
import json
import logging
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from database import woah_db
from database.filters import selection_values, selection_value, selection_label
from slack.multi_filters import multi_element, selected_value
from woah.collector import DISEASES, validate_pdf_url

logger = logging.getLogger(__name__)
POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix='woah-docs')
SLOTS = BoundedSemaphore(6)
PAGE_SIZE = 8


def escape(text):
    return str(text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def section(text):
    return {'type': 'section', 'text': {'type': 'mrkdwn', 'text': text[:2900]}}


def button(label, action, value):
    return {'type': 'button', 'text': {'type': 'plain_text', 'text': label},
            'action_id': action, 'value': value}


def modal(blocks, metadata=None):
    return {'type': 'modal', 'callback_id': 'woah_docs_modal',
            'title': {'type': 'plain_text', 'text': 'WOAH 자체 청정 선언'},
            'close': {'type': 'plain_text', 'text': '닫기'},
            'private_metadata': json.dumps(metadata or {}), 'blocks': blocks}


def loading():
    return modal([section('문서를 확인하고 있습니다.')])


def filtered_documents(docs, start_date=None, end_date=None):
    start = date.fromisoformat(start_date) if start_date else None
    end = date.fromisoformat(end_date) if end_date else None
    if start and end and start > end:
        raise ValueError('시작 날짜는 종료 날짜보다 늦을 수 없습니다.')
    if not start and not end:
        return docs, 0
    result, unknown = [], 0
    for doc in docs:
        try:
            published = date.fromisoformat(str(doc.get('published_date') or ''))
        except ValueError:
            unknown += 1
            continue
        if (not start or published >= start) and (not end or published <= end):
            result.append(doc)
    return result, unknown


def list_view(disease='HPAI', page=0, start_date=None, end_date=None):
    codes = selection_values(disease) or list(DISEASES)
    if any(code not in DISEASES for code in codes):
        raise ValueError('지원하지 않는 질병입니다.')
    source, run = woah_db.list_documents(codes[0] if len(codes) == 1 else None, include_run=True)
    docs, unknown = filtered_documents([doc for doc in source if doc['disease'] in codes], start_date, end_date)
    pages = max(1, (len(docs) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    options = [{'text': {'type': 'plain_text', 'text': code}, 'value': code} for code in DISEASES]
    meta = {'d': disease, 'p': page, 's': start_date, 'e': end_date}
    blocks = [section('*국가가 제출한 자체 청정 선언입니다. WOAH 공식 인정과 구분됩니다.*'),
              {'type': 'actions', 'elements': [{'type': 'multi_static_select',
               'action_id': 'woah_docs_disease', 'options': options,
               'placeholder': {'type': 'plain_text', 'text': '전체 · 질병 검색 및 복수 선택'},
               'initial_options': [option for option in options if option['value'] in selection_values(disease)]}]}]
    if not blocks[1]['elements'][0]['initial_options']:
        blocks[1]['elements'][0].pop('initial_options')
    for block_id, label, selected in (('woah_start', '시작 날짜 (비워두면 전체)', start_date),
                                      ('woah_end', '종료 날짜 (비워두면 전체)', end_date)):
        element = {'type': 'datepicker', 'action_id': 'woah_docs_date',
                   'placeholder': {'type': 'plain_text', 'text': label}}
        if selected:
            element['initial_date'] = selected
        blocks.append({'type': 'actions', 'block_id': block_id, 'elements': [element]})
    blocks.append({'type': 'actions', 'elements': [
        button('날짜 적용 / PDF 조회', 'woah_docs_filter', json.dumps(meta)),
        button('권역별 선언 국가 표', 'woah_docs_countries', json.dumps(meta)),
        button('전체 기간으로 초기화', 'woah_docs_reset', json.dumps(meta))]})
    blocks.append(section(f'게시일 기준 · {start_date or "전체"} ~ {end_date or "전체"}'))
    if unknown:
        blocks.append(section(f'게시일을 확인할 수 없는 문서 {unknown}건은 날짜 조건에서 제외했습니다.'))
    if run:
        blocks.append(section(f'마지막 수집: {run["checked_at"]} UTC · 상태: {escape(run["status"])} · '
                              f'발견 {run["found_count"]}건 / 저장 {run["saved_count"]}건 / 실패 {run["failed_count"]}건'))
        if run['status'] == 'NO_DOCUMENTS':
            blocks.append(section('마지막 정상 조회에서 해당 질병의 공개 문서를 찾지 못했습니다. '
                                  '질병이 없다는 의미는 아닙니다. 기존 보관 문서는 유지됩니다.'))
        elif run['status'] == 'COLLECTION_FAILED':
            blocks.append(section('최신 목록 수집에 실패했습니다. 아래는 기존에 보관한 자료입니다.'))
    elif len(codes) == 1:
        blocks.append(section('아직 수집 이력이 없습니다. 서버에서 woah_main.py를 실행해 주세요.'))
    blocks.append(section(f'*{selection_label(disease)} · 보관 문서 {len(docs)}건 · {page + 1}/{pages} 페이지*'))
    for doc in docs[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        text = (f'*{escape(doc["country"])}* · 게시일: {escape(doc["published_date"])}\n'
                f'{escape(doc["title"])}\nPDF: {escape(doc["download_status"])}')
        if doc['page_count']:
            text += f' · {doc["page_count"]}페이지'
        if doc['latest_version_id'] and doc['download_status'] != 'READY':
            text += '\n최신 다운로드는 실패했지만 이전에 저장된 PDF를 볼 수 있습니다.'
        blocks.append(section(text))
        elements = []
        if doc['latest_version_id']:
            elements.append(button('ChatGPT로 요약하기', 'woah_docs_chatgpt',
                                   json.dumps({'id': doc['id'], **meta})))
        if doc['pdf_url']:
            try:
                validate_pdf_url(doc['pdf_url'])
                elements.append({'type': 'button', 'action_id': 'woah_docs_original',
                                 'text': {'type': 'plain_text', 'text': '원문 PDF'}, 'url': doc['pdf_url']})
            except ValueError:
                pass
        if elements:
            blocks.append({'type': 'actions', 'elements': elements})
        blocks.append({'type': 'divider'})
    nav = []
    if page:
        nav.append(button('이전', 'woah_docs_prev', json.dumps({**meta, 'p': page - 1})))
    if page + 1 < pages:
        nav.append(button('다음', 'woah_docs_next', json.dumps({**meta, 'p': page + 1})))
    if nav:
        blocks.append({'type': 'actions', 'elements': nav})
    return modal(blocks, meta)


def countries_view(disease='HPAI', start_date=None, end_date=None):
    codes = selection_values(disease) or list(DISEASES)
    if any(code not in DISEASES for code in codes):
        raise ValueError('지원하지 않는 질병입니다.')
    source = woah_db.list_declaration_countries(codes[0] if len(codes) == 1 else None)
    docs, unknown = filtered_documents([doc for doc in source if doc['disease'] in codes], start_date, end_date)
    regions = [('Asia', '아시아'), ('Europe', '유럽'), ('Africa', '아프리카'),
               ('America', '아메리카'), ('Oceania', '오세아니아'), ('Other', '기타')]
    grouped = {code: {region: set() for region, _ in regions} for code in
               codes}
    for doc in docs:
        region = doc.get('region')
        if region in ('North America', 'South America'):
            region = 'America'
        if region not in grouped[doc['disease']]:
            region = 'Other'
        grouped[doc['disease']][region].add(doc['country'].strip())
    blocks = [section('*질병별 · 권역별 자체 청정 선언 국가*\n'
                      '보관된 자체 선언 문서의 국가 목록입니다. 지역·구획 선언도 포함하며 현재 국가 전체의 청정 상태나 WOAH 공식 인정을 뜻하지 않습니다.'),
              section(f'*게시일:* {start_date or "전체"} ~ {end_date or "전체"}\n'
                      '*권역 | 선언 국가 (중복 제외)*')]
    if unknown:
        blocks.append(section(f'게시일 미상 문서 {unknown}건은 날짜 조건에서 제외했습니다.'))
    def table_row(region_label, names):
        return {'type': 'section', 'fields': [
            {'type': 'mrkdwn', 'text': f'*{region_label}*'},
            {'type': 'mrkdwn', 'text': names}]}
    for code, countries in grouped.items():
        blocks.append(section(f'*{code}*'))
        blocks.append(table_row('권역', '*선언 국가*'))
        for region, label in regions:
            names = sorted(countries[region])
            # Start a new block between country names, never truncate the list.
            text = ''
            for name in names or ['해당 없음']:
                entry = escape(name)
                if len(text) + len(entry) + 2 > 1800:
                    blocks.append(table_row(label, text))
                    text = ''
                text += (', ' if text else '') + entry
            blocks.append(table_row(label, text))
        blocks.append({'type': 'divider'})
    meta = {'d': disease, 'p': 0, 's': start_date, 'e': end_date}
    blocks.append({'type': 'actions', 'elements': [button('PDF 목록으로', 'woah_docs_back', json.dumps(meta))]})
    return modal(blocks, meta)


def chatgpt_view(document_id, disease, page, start_date=None, end_date=None):
    from woah.chatgpt import SUMMARY_PROMPT
    doc = woah_db.get_document(document_id)
    if not doc or not doc['latest_version_id']:
        raise ValueError('저장된 PDF 원본이 없습니다. 문서 목록에서 다른 문서를 선택해 주세요.')
    blocks = [section(f'*{escape(doc["country"])} · {escape(doc["disease"])}*\n{escape(doc["title"])}'),
              section('1. 원문 PDF를 열고 파일을 내려받으세요.\n'
                      '2. ChatGPT를 열어 PDF를 직접 첨부하세요.\n'
                      '3. 아래 요청문을 복사해 함께 보내세요.\n\n'
                      'PDF와 요청문은 자동 전송되지 않습니다. 요약 결과는 ChatGPT에서 확인합니다.'),
              section('```\n' + SUMMARY_PROMPT + '\n```')]
    elements = []
    if doc.get('pdf_url'):
        try:
            validate_pdf_url(doc['pdf_url'])
            elements.append({'type': 'button', 'action_id': 'woah_docs_original',
                             'text': {'type': 'plain_text', 'text': '원문 PDF'}, 'url': doc['pdf_url']})
        except ValueError:
            pass
    if not elements:
        blocks.append(section(f'현재 사용할 수 있는 원문 링크가 없습니다. 저장된 PDF는 서버에서 '
                              f'woah_main.py --export-id {document_id} 명령으로 내보낼 수 있습니다.'))
    elements.append({'type': 'button', 'action_id': 'woah_docs_chatgpt_link',
                     'text': {'type': 'plain_text', 'text': 'ChatGPT 열기'}, 'url': 'https://chatgpt.com/'})
    blocks.append({'type': 'actions', 'elements': elements})
    blocks.append({'type': 'actions', 'elements': [button('문서 목록으로', 'woah_docs_back',
                   json.dumps({'d': disease, 'p': page, 's': start_date, 'e': end_date}))]})
    return modal(blocks)


def submit(client, view_id, task, metadata=None):
    if not SLOTS.acquire(blocking=False):
        client.views_update(view_id=view_id, view=modal([section('다른 문서를 처리 중입니다. 잠시 후 다시 조회해 주세요.')]))
        return
    def work():
        try:
            try:
                view = task()
            except Exception as exc:
                logger.warning('WOAH modal failed: %s status=%s code=%s',
                               type(exc).__name__, getattr(exc, 'status_code', None),
                               getattr(exc, 'code', None))
                message = str(exc) if isinstance(exc, ValueError) else '문서 조회에 실패했습니다. DB 연결 및 서버 설정을 확인해 주세요.'
                blocks = [section(message)]
                if metadata:
                    blocks.append({'type': 'actions', 'elements': [button('문서 목록으로', 'woah_docs_back', json.dumps(metadata))]})
                view = modal(blocks)
            client.views_update(view_id=view_id, view=view)
        except Exception as exc:
            logger.warning('WOAH view update failed: %s', type(exc).__name__)
        finally:
            SLOTS.release()
    POOL.submit(work)


def register_woah_handlers(app):
    def selected_filters(body):
        meta = json.loads(body['view'].get('private_metadata') or '{}')
        values = body['view'].get('state', {}).get('values', {})
        disease = meta.get('d', 'HPAI')
        for block in values.values():
            if 'woah_docs_disease' in block:
                disease = selected_value(block['woah_docs_disease'])
        start = values.get('woah_start', {}).get('woah_docs_date', {}).get('selected_date', meta.get('s'))
        end = values.get('woah_end', {}).get('woah_docs_date', {}).get('selected_date', meta.get('e'))
        return disease, start, end

    @app.action('woah_docs_date')
    def acknowledge_date(ack):
        ack()

    @app.action('woah_docs_reset')
    def reset_dates(ack, body, client):
        ack()
        disease, _, _ = selected_filters(body)
        client.views_update(view_id=body['view']['id'], view=loading())
        submit(client, body['view']['id'], lambda: list_view(disease))

    @app.action('woah_docs_filter')
    @app.action('woah_docs_countries')
    def apply_filters(ack, body, client):
        ack()
        disease, start, end = selected_filters(body)
        target = countries_view if body['actions'][0]['action_id'] == 'woah_docs_countries' else list_view
        client.views_update(view_id=body['view']['id'], view=loading())
        submit(client, body['view']['id'],
               lambda: target(disease=disease, start_date=start, end_date=end),
               {'d': disease, 'p': 0, 's': start, 'e': end})

    @app.action('woah_docs_original')
    @app.action('woah_docs_chatgpt_link')
    def acknowledge_original_link(ack):
        ack()

    @app.action('woah_docs_open')
    def open_from_stats(ack, body, client):
        ack()
        state = body.get('view', {}).get('state', {}).get('values', {})
        disease = selected_value(state.get('stats_disease_block', {}).get('stats_disease_select', {}))
        response = client.views_push(trigger_id=body['trigger_id'], view=loading())
        submit(client, response['view']['id'], lambda: list_view(disease))

    @app.command('/woah-docs')
    def open_documents(ack, body, client):
        ack()
        requested = (body.get('text') or 'HPAI').strip().upper()
        disease = requested if requested in DISEASES else 'HPAI'
        response = client.views_open(trigger_id=body['trigger_id'], view=loading())
        submit(client, response['view']['id'], lambda: list_view(disease))

    @app.action('woah_docs_disease')
    def change_disease(ack, body, client):
        ack()
        disease = selected_value(body['actions'][0])
        _, start, end = selected_filters(body)
        client.views_update(view_id=body['view']['id'], view=loading())
        submit(client, body['view']['id'], lambda: list_view(disease, start_date=start, end_date=end),
               {'d': disease, 'p': 0, 's': start, 'e': end})

    def navigate(ack, body, client):
        ack()
        meta = json.loads(body['actions'][0]['value'])
        client.views_update(view_id=body['view']['id'], view=loading())
        submit(client, body['view']['id'], lambda: list_view(meta['d'], int(meta['p']), meta.get('s'), meta.get('e')))
    for action in ('woah_docs_prev', 'woah_docs_next', 'woah_docs_back'):
        app.action(action)(navigate)

    @app.action('woah_docs_summary')  # previously opened modals also use the manual workflow
    @app.action('woah_docs_chatgpt')
    def show_chatgpt(ack, body, client):
        ack()
        meta = json.loads(body['actions'][0]['value'])
        client.views_update(view_id=body['view']['id'], view=loading())
        submit(client, body['view']['id'],
               lambda: chatgpt_view(int(meta['id']), meta['d'], int(meta['p']), meta.get('s'), meta.get('e')),
               {k: v for k, v in meta.items() if k != 'id'})
