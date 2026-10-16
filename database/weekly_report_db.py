"""Persist HTML between ephemeral Actions runs and the Railway web server."""

import re
import secrets
from datetime import datetime, timedelta, timezone

from database.db import get_connection

RETENTION_DAYS = 90


def save_weekly_html(html):
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute('''CREATE TABLE IF NOT EXISTS weekly_html_reports (
                token CHAR(43) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
                html MEDIUMTEXT NOT NULL,
                expires_at DATETIME NOT NULL,
                INDEX (expires_at)
            ) CHARACTER SET utf8mb4''')
            cursor.execute('DELETE FROM weekly_html_reports WHERE expires_at <= %s', (now,))
            cursor.execute('INSERT INTO weekly_html_reports (token, html, expires_at) '
                           'VALUES (%s, %s, %s)',
                           (token, html, now + timedelta(days=RETENTION_DAYS)))
        connection.commit()
        return token
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_weekly_html(token):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return None
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT html FROM weekly_html_reports '
                           'WHERE token = %s AND expires_at > %s',
                           (token, datetime.now(timezone.utc).replace(tzinfo=None)))
            row = cursor.fetchone()
            return row[0] if row else None
    finally:
        connection.close()
