"""Read alert details from outbreak-level records, never report total flags."""
from database.db import get_connection


def get_report_alert_details(event):
    result = {'subtype': '미확인', 'animal_category': '미확인', 'species': '미확인',
              'new_outbreaks': '미확인'}
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute('''SELECT dr.subtype, dr.detail_loaded,
                (SELECT COUNT(DISTINCT o.outbreak_id) FROM outbreaks o
                 WHERE o.created_by_report_id=dr.report_id)
                FROM disease_reports dr WHERE dr.report_id=%s''', (event['reportId'],))
            row = cur.fetchone()
            # Failed/unfinished details must not look like zero outbreaks.
            # Creation report remains stable even when the outbreak is updated.
            if row and row[1] == 1:
                result['new_outbreaks'] = f'{row[2]}건'
            if row and row[0] and str(row[0]).strip() not in ('', '-'):
                result['subtype'] = str(row[0]).strip()[:200]
            # Only the outbreaks updated by this report. Do not substitute the
            # event's later or unrelated outbreaks when a queued alert is retried.
            cur.execute('''SELECT o.outbreak_id, o.species_loaded_report_id,
                                  s.species_name, s.is_wild
                FROM outbreaks o LEFT JOIN outbreak_species s
                  ON s.outbreak_id=o.outbreak_id AND s.report_id=%s
                WHERE COALESCE(o.last_update_report_id,o.created_by_report_id)=%s
                ORDER BY o.outbreak_id, s.row_index''',
                (event['reportId'], event['reportId']))
            rows = cur.fetchall()
        flags, names = set(), set()
        unknown = not rows
        for _, loaded_report_id, name, wild in rows:
            if loaded_report_id != event['reportId']:
                unknown = True
                continue
            if wild is None:
                unknown = True
            else:
                flags.add(bool(wild))
            if name and str(name).strip():
                label = '야생' if wild == 1 else '사육' if wild == 0 else '미확인'
                names.add((str(name).strip(), label))
            else:
                unknown = True
        labels = []
        if False in flags:
            labels.append('사육')
        if True in flags:
            labels.append('야생')
        if unknown:
            labels.append('미확인 포함' if labels else '미확인')
        result['animal_category'] = ' / '.join(labels) or '미확인'
        ordered = sorted(names)
        if ordered:
            shown = [f'{name[:100]} ({label})' for name, label in ordered[:10]]
            if len(ordered) > 10:
                shown.append(f'외 {len(ordered) - 10}종')
            result['species'] = ', '.join(shown)
    except Exception as exc:
        # An unavailable enrichment must not suppress the original report alert.
        print(f'Alert detail lookup unavailable: {type(exc).__name__}', flush=True)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return result
