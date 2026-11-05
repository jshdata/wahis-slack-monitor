"""Serialize weekly sends and persist their outcome across ephemeral runners.

Slack has no transaction with MySQL. A send with an unknown outcome is held for
manual review instead of being blindly retried and potentially duplicated.
"""

from zoneinfo import ZoneInfo

from database.db import get_connection


class WeeklyDelivery:
    def __init__(self, end):
        if end.tzinfo is None:
            raise ValueError('Weekly delivery requires a timezone-aware closing date')
        self.week = end.astimezone(ZoneInfo('Asia/Seoul')).date()
        self.lock_name = f'wahis-weekly:{self.week.isoformat()}'
        self.connection = None
        self.locked = False
        self.ready = False
        self.status = 'not_started'

    def __enter__(self):
        self.connection = get_connection()
        try:
            with self.connection.cursor() as cursor:
                cursor.execute('''CREATE TABLE IF NOT EXISTS weekly_digest_deliveries (
                    week_ending DATE PRIMARY KEY,
                    status VARCHAR(16) NOT NULL,
                    updated_at DATETIME NOT NULL
                ) CHARACTER SET utf8mb4''')
            self.connection.commit()
            with self.connection.cursor() as cursor:
                cursor.execute('SELECT GET_LOCK(%s, 0)', (self.lock_name,))
                self.locked = cursor.fetchone()[0] == 1
                if not self.locked:
                    self.status = 'busy'
                    return self
                cursor.execute('SELECT status FROM weekly_digest_deliveries '
                               'WHERE week_ending = %s', (self.week,))
                row = cursor.fetchone()
                self.status = row[0] if row else 'ready'
                self.ready = self.status == 'ready'
            return self
        except Exception:
            self._close()
            raise

    def begin_send(self):
        if not self.ready or not self.locked:
            raise RuntimeError('Weekly send was not claimed')
        # Persist before calling Slack: a killed process must not cause a retry.
        with self.connection.cursor() as cursor:
            cursor.execute('''INSERT INTO weekly_digest_deliveries
                (week_ending, status, updated_at) VALUES (%s, 'sending', UTC_TIMESTAMP())
                ON DUPLICATE KEY UPDATE status = 'sending', updated_at = UTC_TIMESTAMP()''',
                           (self.week,))
        self.connection.commit()
        self.status = 'sending'

    def mark_sent(self):
        with self.connection.cursor() as cursor:
            cursor.execute("UPDATE weekly_digest_deliveries SET status = 'sent', "
                           'updated_at = UTC_TIMESTAMP() WHERE week_ending = %s',
                           (self.week,))
        self.connection.commit()
        self.status = 'sent'

    def _close(self):
        if self.connection is None:
            return
        try:
            if self.locked:
                with self.connection.cursor() as cursor:
                    cursor.execute('SELECT RELEASE_LOCK(%s)', (self.lock_name,))
        except Exception:
            # Closing the connection also releases MySQL named locks.
            print('Weekly delivery lock cleanup failed; closing connection')
        finally:
            self.connection.close()

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.status == 'sending':
                try:
                    with self.connection.cursor() as cursor:
                        cursor.execute("UPDATE weekly_digest_deliveries SET status = 'uncertain', "
                                       'updated_at = UTC_TIMESTAMP() WHERE week_ending = %s',
                                       (self.week,))
                    self.connection.commit()
                except Exception:
                    print('Weekly delivery outcome remains sending; manual review required')
        finally:
            self._close()
        return False


def weekly_delivery(end):
    return WeeklyDelivery(end)
