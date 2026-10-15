"""WOAH document modal. All responses stay in the requesting user's modal."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from database import woah_db
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


def list_view(disease='HPAI', page=0):
    if disease not in DISEASES:
        raise ValueError('지원하지 않는 질병입니다.')
    docs = woah_db.list_documents(disease)
    run = woah_db.latest_run(disease)
    pages = max(1, (len(docs) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    options = [{'text': {'type': 'plain_text', 'text': code}, 'value': code} for code in DISEASES]
    blocks = [section('*국가가 제출한 자체 청정 선언입니다. WOAH 공식 인정과 구분됩니다.*'),
              {'type': 'actions', 'elements': [{'type': 'static_select',
               'action_id': 'woah_docs_disease', 'options': options,
               'initial_option': next(option for option in options if option['value'] == disease)}]}]
    if run:
        blocks.append(section(f'마지막 수집: {run["checked_at"]} UTC · 상태: {escape(run["status"])} · '
                              f'발견 {run["found_count"]}건 / 저장 {run["saved_count"]}건 / 실패 {run["failed_count"]}건'))
        if run['status'] == 'NO_DOCUMENTS':
            blocks.append(section('마지막 정상 조회에서 해당 질병의 공개 문서를 찾지 못했습니다. '
                                  '질병이 없다는 의미는 아닙니다. 기존 보관 문서는 유지됩니다.'))
        elif run['status'] == 'COLLECTION_FAILED':
            blocks.append(section('최신 목록 수집에 실패했습니다. 아래는 기존에 보관한 자료입니다.'))
    else:
        blocks.append(section('아직 수집 이력이 없습니다. 서버에서 woah_main.py를 실행해 주세요.'))
    blocks.append(section(f'*{disease} · 보관 문서 {len(docs)}건 · {page + 1}/{pages} 페이지*'))
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
                                   json.dumps({'id': doc['id'], 'd': disease, 'p': page})))
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
        nav.append(button('이전', 'woah_docs_prev', json.dumps({'d': disease, 'p': page - 1})))
    if page + 1 < pages:
        nav.append(button('다음', 'woah_docs_next', json.dumps({'d': disease, 'p': page + 1})))
    if nav:
        blocks.append({'type': 'actions', 'elements': nav})
    return modal(blocks, {'d': disease, 'p': page})


def chatgpt_view(document_id, disease, page):
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
                   json.dumps({'d': disease, 'p': page}))]})
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
    @app.action('woah_docs_original')
    @app.action('woah_docs_chatgpt_link')
    def acknowledge_original_link(ack):
        ack()

    @app.action('woah_docs_open')
    def open_from_stats(ack, body, client):
        ack()
        state = body.get('view', {}).get('state', {}).get('values', {})
        selected = state.get('stats_disease_block', {}).get('stats_disease_select', {}).get('selected_option') or {}
        disease = selected.get('value', 'HPAI')
        if disease not in DISEASES:
            disease = 'HPAI'
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
        disease = body['actions'][0]['selected_option']['value']
        client.views_update(view_id=body['view']['id'], view=loading())
        submit(client, body['view']['id'], lambda: list_view(disease))

    def navigate(ack, body, client):
        ack()
        meta = json.loads(body['actions'][0]['value'])
        client.views_update(view_id=body['view']['id'], view=loading())
        submit(client, body['view']['id'], lambda: list_view(meta['d'], int(meta['p'])))
    for action in ('woah_docs_prev', 'woah_docs_next', 'woah_docs_back'):
        app.action(action)(navigate)

    @app.action('woah_docs_summary')  # previously opened modals also use the manual workflow
    @app.action('woah_docs_chatgpt')
    def show_chatgpt(ack, body, client):
        ack()
        meta = json.loads(body['actions'][0]['value'])
        client.views_update(view_id=body['view']['id'], view=loading())
        submit(client, body['view']['id'],
               lambda: chatgpt_view(int(meta['id']), meta['d'], int(meta['p'])),
               {'d': meta['d'], 'p': meta['p']})
