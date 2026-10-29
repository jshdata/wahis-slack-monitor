"""Read-only report map and deduplicated country/disease history."""

from collections import Counter
from datetime import timedelta
import math

import pymysql
from database.db import get_connection


def valid_coordinates(latitude, longitude):
    try:
        lat, lon = float(latitude), float(longitude)
        return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
    except (TypeError, ValueError):
        return False


def load_report_dashboard(report_id, days=90):
    report_id = int(report_id)
    if report_id <= 0 or days not in (30, 90, 365):
        raise ValueError('Invalid report or period')
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute('''SELECT report_id, event_id, country, disease, submission_date,
                           report_type, event_status, detail_loaded
                           FROM disease_reports WHERE report_id=%s''', (report_id,))
            report = cur.fetchone()
            if not report:
                return None
            # Membership is only recoverable for creation and latest update.
            # Never label every outbreak in the event as belonging to this report.
            cur.execute('''SELECT outbreak_id, created_by_report_id, last_update_report_id,
                           location, admin_division, location_approx, start_date,
                           latitude, longitude, epi_unit_type, cluster_count,
                           end_date, description FROM outbreaks
                           WHERE created_by_report_id=%s OR
                           COALESCE(last_update_report_id,created_by_report_id)=%s
                           ORDER BY outbreak_id''', (report_id, report_id))
            outbreaks = cur.fetchall()
            for row in outbreaks:
                row['kind'] = '신규' if row['created_by_report_id'] == report_id else '기존 발생 갱신'
                row['mapped'] = valid_coordinates(row['latitude'], row['longitude'])
            submitted = report['submission_date']
            if submitted is None:
                return {'report': report, 'outbreaks': outbreaks, 'trend': [], 'start': None, 'end': None}
            end = submitted.date() if hasattr(submitted, 'date') else submitted
            start = end - timedelta(days=days - 1)
            # EXISTS avoids multiplying an outbreak by all follow-up reports.
            cur.execute('''SELECT DATE(o.start_date) AS day, COUNT(*) AS count
                           FROM outbreaks o WHERE o.start_date >= %s AND o.start_date < %s
                           AND EXISTS (SELECT 1 FROM disease_reports dr
                             WHERE dr.event_id=o.event_id AND dr.country=%s AND dr.disease=%s)
                           GROUP BY DATE(o.start_date) ORDER BY day''',
                        (start, end + timedelta(days=1), report['country'], report['disease']))
            counts = Counter({row['day']: row['count'] for row in cur.fetchall()})
            trend = [{'발생일': start + timedelta(days=i),
                      '발생 건수': counts[start + timedelta(days=i)]} for i in range(days)]
            return {'report': report, 'outbreaks': outbreaks, 'trend': trend, 'start': start, 'end': end}
    finally:
        conn.close()
