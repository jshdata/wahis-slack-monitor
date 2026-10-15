"""Fixed neighboring-country groups; China and Hong Kong share one group."""

from datetime import datetime
from zoneinfo import ZoneInfo

from database.db import get_connection
from database.stats_db import DISEASE_MAP

NEIGHBORS = [
    ('네팔', ('Nepal',)), ('동티모르', ('Timor-Leste', 'East Timor')),
    ('라오스', ('Laos', "Lao People's Democratic Republic")),
    ('말레이시아', ('Malaysia',)), ('몽골', ('Mongolia',)), ('미얀마', ('Myanmar',)),
    ('방글라데시', ('Bangladesh',)), ('베트남', ('Vietnam', 'Viet Nam')),
    ('부탄', ('Bhutan',)), ('북한', ("Korea (Dem People's Rep. of)", 'North Korea')),
    ('스리랑카', ('Sri Lanka',)), ('싱가포르', ('Singapore',)), ('인도', ('India',)),
    ('인도네시아', ('Indonesia',)),
    ('중국(본토·홍콩)', ("China (People's Rep. of)", 'China', 'Hong Kong')),
    ('캄보디아', ('Cambodia',)), ('태국', ('Thailand',)), ('필리핀', ('Philippines',)),
]


def get_neighbor_stats(selection, start_date=None, end_date=None):
    codes = ['HPAI', 'HPAI_NON_POULTRY'] if selection == 'HPAI' else [selection]
    if any(code not in DISEASE_MAP for code in codes):
        raise ValueError('지원하지 않는 질병입니다.')
    today = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    end = end_date or today
    aliases = [alias for _, names in NEIGHBORS for alias in names]
    names = [DISEASE_MAP[code] for code in codes]
    filters = (f"dr.disease IN ({','.join(['%s'] * len(names))}) AND "
               f"dr.country IN ({','.join(['%s'] * len(aliases))})")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if start_date:
                start = start_date
            else:
                cursor.execute(f"""SELECT DATE(MIN(o.start_date)) FROM outbreaks o
                    JOIN disease_reports dr ON dr.event_id=o.event_id WHERE {filters}""", names + aliases)
                first = cursor.fetchone()[0]
                start = min(first.isoformat() if first else end, end)
            if start > end:
                raise ValueError('종료일은 시작일보다 빠를 수 없습니다.')
            cases, case_params = [], []
            for index, (_, variants) in enumerate(NEIGHBORS):
                cases.append(f"WHEN dr.country IN ({','.join(['%s'] * len(variants))}) THEN {index}")
                case_params.extend(variants)
            cursor.execute(f"""SELECT TRIM(dr.disease), CASE {' '.join(cases)} END AS country_index,
                    COUNT(DISTINCT o.outbreak_id), DATE(MAX(o.start_date))
                FROM outbreaks o JOIN disease_reports dr ON dr.event_id=o.event_id
                WHERE {filters} AND o.start_date >= %s
                  AND o.start_date < DATE_ADD(%s, INTERVAL 1 DAY)
                GROUP BY dr.disease,country_index""", case_params + names + aliases + [start, end])
            rows = cursor.fetchall()
        results = {code: [{'country': label, 'count': 0, 'latest': None} for label, _ in NEIGHBORS]
                   for code in codes}
        lookup = {DISEASE_MAP[code].strip(): code for code in codes}
        for disease, index, count, latest in rows:
            results[lookup[disease]][int(index)].update(count=int(count), latest=latest.isoformat() if latest else None)
        return {'start': start, 'end': end, 'diseases': results}
    finally:
        conn.close()
