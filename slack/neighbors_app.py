"""Neighbor occurrence analysis in a modal with an optional full HTML table."""

import logging
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from html import escape
from threading import BoundedSemaphore
from uuid import uuid4
from zoneinfo import ZoneInfo

from database.neighbors_db import get_neighbor_stats
from slack.stats_report_server import REPORT_TTL_SECONDS, report_url

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='neighbors')
SLOTS = BoundedSemaphore(4)
logger = logging.getLogger(__name__)


def modal(blocks, settings=False):
    view = {'type': 'modal', 'title': {'type': 'plain_text', 'text': '주변국 발생현황'},
            'close': {'type': 'plain_text', 'text': '닫기'}, 'blocks': blocks}
    if settings:
        view.update(callback_id='neighbors_settings', submit={'type': 'plain_text', 'text': '조회하기'})
    return view


def section(text):
    return {'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}}


def settings_view(disease='ASF'):
    options = [{'text': {'type': 'plain_text', 'text': code}, 'value': code}
               for code in ('HPAI', 'ASF', 'FMD', 'LSD', 'BSE')]
    blocks = [section('지정한 18개국을 고정 조회합니다. 중국 본토·홍콩은 한 행으로 합산합니다.\n'
                      '발생일 기준 고유 outbreak 수와 선택 기간 내 최근 발생일을 표시합니다.')]
    blocks.append({'type': 'input', 'block_id': 'neighbors_disease',
                   'label': {'type': 'plain_text', 'text': '질병'},
                   'element': {'type': 'static_select', 'action_id': 'select', 'options': options,
                               'initial_option': next(o for o in options if o['value'] == disease)}})
    for block, label in [('neighbors_start', '시작일 (미선택 시 최초 발생일)'),
                         ('neighbors_end', '종료일 (미선택 시 오늘·한국시간)')]:
        blocks.append({'type': 'input', 'optional': True, 'block_id': block,
                       'label': {'type': 'plain_text', 'text': label},
                       'element': {'type': 'datepicker', 'action_id': 'date'}})
    return modal(blocks, settings=True)


def title(code):
    if code == 'HPAI':
        return '주변국 HPAI 발생현황 - 가금'
    if code == 'HPAI_NON_POULTRY':
        return '주변국 HPAI 발생현황 - 가금 외'
    return f'주변국 {code} 발생현황'


def pad(text, width):
    size = sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)
    return text + ' ' * max(0, width - size)


def result_blocks(result):
    blocks = [section(f'*조회기간:* {result["start"]} ~ {result["end"]}\n'
                      '고정 18개국 · 중국 본토·홍콩 합산 · 최근 발생일은 선택 기간 내 기준')]
    for code, rows in result['diseases'].items():
        lines = [pad('국가', 18) + ' 발생건수 최근 발생일', '-' * 38]
        for row in rows:
            lines.append(pad(row['country'], 18) + f' {row["count"]:>8,} {row["latest"] or "—"}')
        lines.extend(['-' * 38, pad('합계', 18) + f' {sum(r["count"] for r in rows):>8,}'])
        blocks.extend([section(f'*{title(code)}*'), section('```\n' + '\n'.join(lines) + '\n```')])
    return blocks


def build_neighbor_report(result):
    tables = []
    for code, rows in result['diseases'].items():
        body = ''.join(f'<tr><td>{escape(row["country"])}</td><td>{row["count"]:,}</td>'
                       f'<td>{row["latest"] or "—"}</td></tr>' for row in rows)
        total = sum(row['count'] for row in rows)
        tables.append(f'<h2>{title(code)}</h2><table><thead><tr><th>국가</th><th>발생건수</th>'
                      f'<th>최근 발생일</th></tr></thead><tbody>{body}</tbody>'
                      f'<tfoot><tr><th>합계</th><td>{total:,}</td><td></td></tr></tfoot></table>')
    return '''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>주변국 발생현황</title>
<style>body{font:16px system-ui,sans-serif;margin:24px;color:#172033;background:#f4f6fa}
table{border-collapse:collapse;width:100%;max-width:1000px;background:white;margin-bottom:32px}
th,td{border:1px solid #ccd4df;padding:12px;text-align:right}th:first-child,td:first-child{text-align:left}
thead{background:#183553;color:white}tfoot{background:#dce9f7;font-weight:bold}p{line-height:1.6}</style>
<h1>주변국 발생현황</h1>''' + f'<p>조회기간: {result["start"]} ~ {result["end"]}<br>' + (
        '고정 18개국 · 중국 본토·홍콩 합산 · 발생일(outbreak.start_date) 기준 고유 outbreak 수<br>'
        '최근 발생일은 선택 기간 내 마지막 발생일입니다. 0건은 해당 기간에 저장된 발생 기록이 없음을 뜻합니다.</p>') + ''.join(tables) + '</html>'


def register_neighbor_handlers(app, reports):
    @app.action('neighbors_open')
    def open_settings(ack, body, client):
        ack()
        values = body['view'].get('state', {}).get('values', {})
        selected = values.get('stats_disease_block', {}).get('stats_disease_select', {}).get('selected_option') or {}
        disease = selected.get('value', 'ASF')
        if disease not in ('HPAI', 'ASF', 'FMD', 'LSD', 'BSE'):
            disease = 'ASF'
        client.views_push(trigger_id=body['trigger_id'], view=settings_view(disease))

    @app.action('neighbors_report_link')
    def acknowledge_link(ack):
        ack()

    @app.view('neighbors_settings')
    def generate(ack, body, view, client):
        values = view['state']['values']
        disease = values['neighbors_disease']['select']['selected_option']['value']
        start = values.get('neighbors_start', {}).get('date', {}).get('selected_date')
        end = values.get('neighbors_end', {}).get('date', {}).get('selected_date')
        errors = {}
        for value, block in [(start, 'neighbors_start'), (end, 'neighbors_end')]:
            try:
                if value:
                    date.fromisoformat(value)
            except ValueError:
                errors[block] = '유효한 날짜를 선택해주세요.'
        effective_end = end or datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
        if start and start > effective_end:
            errors['neighbors_end'] = '종료일은 시작일보다 빠를 수 없습니다.'
        if disease not in ('HPAI', 'ASF', 'FMD', 'LSD', 'BSE'):
            errors['neighbors_disease'] = '지원하지 않는 질병입니다.'
        if errors:
            ack(response_action='errors', errors=errors)
            return
        if not SLOTS.acquire(blocking=False):
            ack(response_action='errors', errors={'neighbors_disease': '잠시 후 다시 조회해주세요.'})
            return
        ack(response_action='update', view=modal([section('주변국 발생현황을 조회하고 있습니다.')]))

        def work():
            try:
                result = get_neighbor_stats(disease, start, end)
                blocks = result_blocks(result)
                key = uuid4().hex
                url = report_url(key)
                if url:
                    reports[key] = {'html': build_neighbor_report(result), 'expires_at': time.time() + REPORT_TTL_SECONDS}
                    while len(reports) > 30:
                        reports.pop(next(iter(reports)), None)
                    blocks.append({'type': 'actions', 'elements': [{'type': 'button',
                        'action_id': 'neighbors_report_link', 'url': url,
                        'text': {'type': 'plain_text', 'text': '큰 표 열기'}}]})
                output = modal(blocks)
            except Exception as error:
                logger.warning('Neighbor report failed: %s', type(error).__name__)
                output = modal([section(str(error) if isinstance(error, ValueError) else
                                        '조회에 실패했습니다. DB 연결 및 서버 로그를 확인해주세요.')])
            finally:
                SLOTS.release()
            try:
                client.views_update(view_id=body['view']['id'], view=output)
            except Exception as error:
                logger.warning('Neighbor modal update failed: %s', type(error).__name__)
        POOL.submit(work)
