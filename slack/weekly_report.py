"""Weekly WAHIS digest using stored report submission times (UTC)."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pymysql

from database.db import get_connection
from slack.notifier import get_reason_label, send_slack_message
from database.weekly_report_db import save_weekly_html

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
                SELECT dr.report_id, dr.event_id, dr.country, dr.disease, dr.submission_date,
                       dr.report_type, dr.reason, dr.event_status, dr.subtype,
                       dr.slack_event_json, dr.detail_loaded, dr.report_number,
                       (SELECT COUNT(*) FROM outbreaks o
                        WHERE o.created_by_report_id = dr.report_id) AS new_outbreak_count
                FROM disease_reports dr
                WHERE submission_date >= %s AND submission_date < %s
                ORDER BY country, disease, submission_date, report_id
            ''', (start.astimezone(timezone.utc).replace(tzinfo=None),
                  end.astimezone(timezone.utc).replace(tzinfo=None)))
            return cursor.fetchall()
    finally:
        connection.close()


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


def report_kind(report):
    value = report_value(report, 'report_type', 'reportType').lower()
    if value == 'fur' or 'follow' in value:
        return '후속 리포트'
    if value == 'in' or 'immediate' in value or 'initial' in value:
        return '최초 리포트'
    if report.get('report_number') is not None:
        return '최초 리포트' if int(report['report_number']) == 0 else '후속 리포트'
    return '기타·미확인'


def outbreak_count(report):
    if not report.get('detail_loaded'):
        return None
    return int(report.get('new_outbreak_count') or 0)


def summary(reports):
    known = [outbreak_count(r) for r in reports]
    return dict(
        reports=len(reports), countries=len({r['country'] for r in reports}),
        diseases=len({r['disease'] for r in reports}),
        followups=sum(report_kind(r) == '후속 리포트' for r in reports),
        initial=sum(report_kind(r) == '최초 리포트' for r in reports),
        unknown=sum(report_kind(r) == '기타·미확인' for r in reports),
        outbreaks=sum(value for value in known if value is not None),
        incomplete=sum(value is None for value in known),
    )


def build_weekly_messages(reports, start, end):
    counts = summary(reports)
    text = (
        '*📋 WAHIS 주간 리포트 요약*\n'
        f'{start:%Y-%m-%d %H:%M} ~ {end - timedelta(seconds=1):%Y-%m-%d %H:%M} (서울시간)\n'
        f'*리포트 {counts["reports"]:,}건* · 국가 {counts["countries"]:,}개 · '
        f'질병 {counts["diseases"]:,}개\n'
        f'최초 {counts["initial"]:,}건 · 후속 리포트 {counts["followups"]:,}건 · 추가 발생 {counts["outbreaks"]:,}건'
    )
    if counts['incomplete']:
        text += f' (상세 미수집 {counts["incomplete"]}개 리포트 제외)'
    if counts['unknown']:
        text += f'\n보고 구분 미확인 {counts["unknown"]}건'
    if not reports:
        text += '\n해당 기간에 제출된 신규 리포트가 없습니다.'
    return [text]


def weekly_public_base():
    base = (os.getenv('WEEKLY_REPORT_BASE_URL') or os.getenv('STATS_REPORT_BASE_URL')
            or 'https://wahis-slack-monitor-production.up.railway.app').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.hostname == 'railway.com':
        raise ValueError('WEEKLY_REPORT_BASE_URL에는 앱의 HTTPS 공개 주소가 필요합니다.')
    return base


def send_weekly_report(start, end, dry_run=False, output_path=None):
    from slack.weekly_html import build_weekly_html

    reports = load_weekly_reports(start, end)
    html = build_weekly_html(reports, start, end)
    if output_path:
        Path(output_path).write_text(html, encoding='utf-8')
    text = build_weekly_messages(reports, start, end)[0]
    if dry_run:
        print(text)
    else:
        base = weekly_public_base()
        token = save_weekly_html(html)
        url = f'{base}/weekly/{token}'
        send_slack_message([
            {'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}},
            {'type': 'actions', 'elements': [{
                'type': 'button', 'text': {'type': 'plain_text', 'text': '주간 상세 HTML 보기'},
                'url': url, 'action_id': 'weekly_report_open',
            }]},
        ], text=text)
    return len(reports)
