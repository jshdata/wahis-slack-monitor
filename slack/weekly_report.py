"""Weekly WAHIS digest using stored report submission times (UTC)."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

import pymysql

from database.db import get_connection
from slack.notifier import get_reason_label, send_slack_message

KST = ZoneInfo('Asia/Seoul')


def weekly_window(now=None, week_ending=None):
    """Return [previous Thursday 09:00, Thursday 09:00) in Seoul time."""
    if week_ending:
        end = datetime.strptime(week_ending, '%Y-%m-%d').replace(
            hour=9, tzinfo=KST)
        if end.weekday() != 3:
            raise ValueError('종료 날짜는 목요일이어야 합니다.')
    else:
        now = now or datetime.now(KST)
        if now.tzinfo is None:
            raise ValueError('현재 시각에는 시간대가 필요합니다.')
        local = now.astimezone(KST)
        end = local.replace(hour=9, minute=0, second=0, microsecond=0)
        end -= timedelta(days=(local.weekday() - 3) % 7)
        if end > local:
            end -= timedelta(days=7)
    return end - timedelta(days=7), end


def load_weekly_reports(start, end):
    connection = get_connection()
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute('''
                SELECT report_id, event_id, country, disease, submission_date,
                       report_type, reason, event_status, subtype, slack_event_json
                FROM disease_reports
                WHERE submission_date >= %s AND submission_date < %s
                ORDER BY country, disease, submission_date, report_id
            ''', (start.astimezone(timezone.utc).replace(tzinfo=None),
                  end.astimezone(timezone.utc).replace(tzinfo=None)))
            return cursor.fetchall()
    finally:
        connection.close()


def escape(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def report_value(report, key, event_key):
    if report.get(key):
        return str(report[key])
    raw = report.get('slack_event_json')
    try:
        event = json.loads(raw) if isinstance(raw, str) else (raw or {})
        value = event.get(event_key)
        if isinstance(value, dict):
            value = value.get('translation') or value.get('name')
        return str(value) if value else '미확인'
    except (ValueError, TypeError, AttributeError):
        return '미확인'


def build_weekly_messages(reports, start, end):
    """Render every report, splitting messages to stay within Slack limits."""
    countries = {r['country'] for r in reports}
    diseases = Counter(r['disease'] for r in reports)
    events = {r['event_id'] for r in reports if r.get('event_id') is not None}
    lines = [
        '*📋 WAHIS 주간 신규 리포트 요약*',
        f'*기간 (서울시간):* {start:%Y-%m-%d %H:%M} ~ '
        f'{end - timedelta(seconds=1):%Y-%m-%d %H:%M:%S}',
        '*기준:* WAHIS 제출시각 · 신규 제출 및 후속 리포트 포함',
        f'*전체:* 리포트 {len(reports):,}건 · 국가 {len(countries):,}개 · '
        f'질병 {len(diseases):,}개 · 이벤트 {len(events):,}개',
        '※ 같은 이벤트의 후속 보고는 별도 리포트이며, 신규 발생건수를 뜻하지 않습니다.',
        '',
    ]
    if not reports:
        lines.append('해당 기간에 제출된 신규 리포트가 없습니다.')
    else:
        lines.append('*질병별 현황*')
        for disease, count in diseases.most_common():
            lines.append(f'• {escape(disease)}: {count:,}건')
        groups = defaultdict(list)
        for report in reports:
            groups[(report['country'], report['disease'])].append(report)
        lines.extend(['', '*국가·질병별 보고 내용*'])
        for (country, disease), items in sorted(groups.items()):
            lines.append(f'\n*{escape(country)} · {escape(disease)} — {len(items):,}건*')
            types = Counter(report_value(r, 'report_type', 'reportType') for r in items)
            reasons = Counter(get_reason_label(report_value(r, 'reason', 'reason')) for r in items)
            lines.append('보고 유형: ' + ' / '.join(f'{escape(k)} {v}건' for k, v in types.items()))
            lines.append('발생 사유: ' + ' / '.join(f'{escape(k)} {v}건' for k, v in reasons.items()))
            for report in items:
                submitted = report['submission_date'].replace(tzinfo=timezone.utc).astimezone(KST)
                url = (f"https://wahis.woah.org/#/in-review/{int(report['event_id'])}"
                       f"?reportId={int(report['report_id'])}&fromPage=event-dashboard-url")
                status = report_value(report, 'event_status', 'eventStatus')
                subtype = report.get('subtype') or '미확인'
                lines.append(f'• <{url}|Report {report["report_id"]}> · {submitted:%m-%d %H:%M} · '
                             f'유형 {escape(subtype)} · 상태 {escape(status)}')
    chunks = []
    current = ''
    for line in lines:
        # API-sourced free text can be long. Split rather than omit it.
        while len(line) > 2700:
            if current:
                chunks.append(current)
                current = ''
            chunks.append(line[:2700])
            line = line[2700:]
        if len(current) + len(line) + 1 > 2800:
            chunks.append(current)
            current = ''
        current += ('\n' if current else '') + line
    if current:
        chunks.append(current)
    return chunks


def send_weekly_report(start, end, dry_run=False):
    reports = load_weekly_reports(start, end)
    messages = build_weekly_messages(reports, start, end)
    for number, message in enumerate(messages, 1):
        text = f'WAHIS 주간 요약 ({number}/{len(messages)})\n{message}'
        if dry_run:
            print(text)
        else:
            send_slack_message(
                [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}}],
                text=text)
    return len(reports)
