"""Stream source rows without disk-backed SQL aggregation or follow-up duplication."""

from collections import Counter
from datetime import timedelta

import pymysql

from database.db import get_connection
from database.regions import KNOWN_REGIONS
from database.stats_db import DISEASE_MAP


def load_dashboard_data(today):
    codes = {name.strip().casefold(): code for code, name in DISEASE_MAP.items()}
    connection = get_connection()
    try:
        # One event may have hundreds of follow-up reports. Keep one metadata
        # record per event before touching outbreaks; never join all reports.
        events = {}
        regions = {}
        counts = Counter()
        with connection.cursor(pymysql.cursors.SSCursor) as cursor:
            cursor.execute(f"SELECT event_id, country, disease FROM disease_reports "
                           f"WHERE disease IN ({','.join(['%s'] * len(codes))})", list(DISEASE_MAP.values()))
            for event_id, country, disease in cursor:
                metadata = (country or 'Unknown', codes[disease.strip().casefold()])
                events[event_id] = max(events.get(event_id, metadata), metadata)
            cursor.execute('SELECT country, region FROM country_regions')
            for country, region in cursor:
                normalized = region if region in KNOWN_REGIONS else 'Other'
                regions[country] = max(regions.get(country, normalized), normalized)
            # outbreaks has one row per outbreak_id. Streaming avoids retaining
            # every raw outbreak in memory and avoids MySQL temporary sort files.
            cursor.execute('SELECT DATE(start_date), event_id FROM outbreaks '
                           'WHERE start_date IS NOT NULL AND start_date < %s',
                           (today + timedelta(days=1),))
            for day, event_id in cursor:
                metadata = events.get(event_id)
                if metadata:
                    country, disease = metadata
                    counts[(day.isoformat(), country, regions.get(country, 'Other'), disease)] += 1
        return [[*key, count] for key, count in sorted(counts.items())]
    finally:
        connection.close()
