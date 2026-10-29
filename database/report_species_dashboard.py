"""Report-version-aware species counts; counts are outbreak sites, not animals."""
from collections import Counter

import pymysql
from database.db import get_connection


def summarize_species(rows, report_id):
    grouped = {}
    for row in rows:
        entry = grouped.setdefault(row['outbreak_id'], {'flags': set(), 'names': set(),
                                                        'unknown': False})
        if row['species_loaded_report_id'] != report_id or row['species_report_id'] != report_id:
            entry['unknown'] = True
            continue
        flag, name = row['is_wild'], row['species_name']
        if flag is None:
            entry['unknown'] = True
        else:
            entry['flags'].add(bool(flag))
        if name and name.strip():
            entry['names'].add(name.strip())
    categories = Counter({'사육': 0, '야생': 0, '혼합': 0, '미확인': 0})
    species = Counter()
    sites = {}
    for oid, entry in grouped.items():
        flags = entry['flags']
        category = ('미확인' if entry['unknown'] or not flags else
                    '혼합' if len(flags) == 2 else '야생' if True in flags else '사육')
        categories[category] += 1
        species.update(entry['names'])  # one site per distinct species, never row count
        sites[oid] = {'category': category, 'species': ', '.join(sorted(entry['names'])) or '미확인'}
    return {'sites': sites, 'categories': dict(categories),
            'species': [{'축종': name, '발생지 수': count} for name, count in species.most_common()]}


def load_report_species(report_id):
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute('''SELECT o.outbreak_id, o.species_loaded_report_id,
                                  s.report_id AS species_report_id, s.species_name, s.is_wild
                FROM outbreaks o LEFT JOIN outbreak_species s
                  ON s.outbreak_id=o.outbreak_id AND s.report_id=%s
                WHERE o.created_by_report_id=%s OR
                      COALESCE(o.last_update_report_id,o.created_by_report_id)=%s
                ORDER BY o.outbreak_id, s.row_index''', (report_id, report_id, report_id))
            return summarize_species(cur.fetchall(), report_id)
    finally:
        conn.close()
