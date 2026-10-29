"""Report-level quantities, never joined to individual outbreak IDs."""
import pymysql
from database.db import get_connection

FIELDS = {'cases': '감염', 'deaths': '폐사', 'killed': '살처분',
          'slaughtered': '도축', 'vaccinated': '예방접종', 'susceptible': '감수성 동물'}


def quantity_summary(rows):
    result = {}
    for field in FIELDS:
        known = [float(row[field]) for row in rows if row.get(field) is not None]
        result[field] = {'value': sum(known) if known else None,
                         'missing': len(rows) - len(known)}
    return result


def format_quantity(item):
    if item['value'] is None:
        return '미보고'
    value = f"{item['value']:,.0f}" if item['value'].is_integer() else f"{item['value']:,.2f}"
    return value + (' (일부 미보고)' if item['missing'] else '')


def species_quantities(rows):
    groups = {}
    for row in rows:
        key = (row.get('species_name') or '미확인', row.get('is_wild'))
        groups.setdefault(key, []).append(row)
    table, chart = [], []
    for (name, wild), items in groups.items():
        category = '미확인' if wild is None else '야생' if wild else '사육'
        summary = quantity_summary(items)
        table.append({'축종': name, '사육·야생': category,
                      **{label: format_quantity(summary[field]) for field, label in FIELDS.items()}})
        for field in ('cases', 'deaths', 'killed'):
            if summary[field]['value'] is not None:
                chart.append({'축종·구분': f'{name} ({category})', '항목': FIELDS[field],
                              '수량': summary[field]['value'],
                              '자료 상태': '일부 미보고' if summary[field]['missing'] else '보고됨'})
    return table, chart


def load_report_quantities(report_id):
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute('''SELECT data_type, species_name, is_wild, unit,
                susceptible, cases, deaths, killed, slaughtered, vaccinated
                FROM report_quantitative WHERE report_id=%s
                ORDER BY data_type, species_name, is_wild, outbreak_quantities_id''', (report_id,))
            rows = cur.fetchall()
            for row in rows:
                row['unit'] = (row['unit'] or '').strip() or '단위 미확인'
            return rows
    finally:
        conn.close()
