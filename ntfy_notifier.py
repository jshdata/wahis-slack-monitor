"""Optional ntfy delivery with an independent, persistent outbox."""

import json
import os

import requests
from database.report_alert_details import get_report_alert_details


def enabled():
    return bool(os.getenv('NTFY_TOPIC_URL', '').strip())


def initialize():
    from database.db import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''CREATE TABLE IF NOT EXISTS ntfy_outbox (
                report_id BIGINT PRIMARY KEY,
                event_json LONGTEXT NOT NULL,
                topic_url TEXT NOT NULL,
                sent TINYINT NOT NULL DEFAULT 0,
                attempts INT NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP NULL
            )''')
        conn.commit()
    finally:
        conn.close()


def enqueue(cursor, event):
    """Called inside the report insert transaction; never resets delivery state."""
    if enabled():
        cursor.execute('''INSERT IGNORE INTO ntfy_outbox
            (report_id, event_json, topic_url) VALUES (%s, %s, %s)''',
            (event['reportId'], json.dumps(event, ensure_ascii=False, default=str),
             os.environ['NTFY_TOPIC_URL'].strip()))


def send(event, topic_url):
    details = get_report_alert_details(event)
    url = (f"https://wahis.woah.org/#/in-review/{event['eventId']}"
           f"?reportId={event['reportId']}&fromPage=event-dashboard-url")
    headers = {}
    token = os.getenv('NTFY_TOKEN', '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    # JSON supports Unicode titles without HTTP header encoding issues.
    server, topic = topic_url.rstrip('/').rsplit('/', 1)
    response = requests.post(server, json={
        'topic': topic,
        'title': f"WAHIS 신규 보고: {event.get('country', '-')} / {event.get('disease', '-')}",
        'message': '\n'.join([
            f"국가: {event.get('country', '-')}",
            f"질병: {event.get('disease', '-')}",
            f"신규 발생: {details['new_outbreaks']}",
            f"혈청형·아형: {details['subtype']}",
            f"사육·야생 구분: {details['animal_category']}",
            f"축종: {details['species']}",
            '축종·구분: 이번 보고로 갱신된 발생지 중 확인된 자료 기준',
            f"Report ID: {event['reportId']}",
            f"보고 유형: {event.get('reportType') or '-'}",
            f"제출일: {event.get('submissionDate') or '-'}",
            f"발생 사유: {event.get('reason') or '-'}",
        ]),
        'click': url,
    }, headers=headers, timeout=15)
    response.raise_for_status()


def deliver_pending(reporter, limit=20):
    if not enabled():
        return
    from database.db import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('''SELECT report_id, event_json, topic_url FROM ntfy_outbox
                WHERE sent = 0 AND attempts < 5
                ORDER BY created_at, report_id LIMIT %s''', (limit,))
            rows = cursor.fetchall()
        for report_id, event_json, topic_url in rows:
            try:
                send(json.loads(event_json), topic_url)
            except Exception as exc:
                # Avoid including request URLs or authorization details in alerts.
                reporter.record('ntfy 전송 실패', RuntimeError(type(exc).__name__),
                                report_id=report_id)
                with conn.cursor() as cursor:
                    cursor.execute('UPDATE ntfy_outbox SET attempts = attempts + 1 WHERE report_id = %s',
                                   (report_id,))
            else:
                with conn.cursor() as cursor:
                    cursor.execute('''UPDATE ntfy_outbox SET sent = 1,
                        sent_at = UTC_TIMESTAMP() WHERE report_id = %s''', (report_id,))
                print(f'ntfy 전송 완료: report_id={report_id}')
            conn.commit()
    finally:
        conn.close()
