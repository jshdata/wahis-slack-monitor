"""Country/month occurrence facts, deduplicated across reports and outbreaks."""

from database.db import get_connection
from database.stats_db import DISEASE_MAP
from database.filters import selection_values


def disease_codes(selection):
    if isinstance(selection, (list, tuple)):
        return list(dict.fromkeys(code for item in (selection_values(selection) or ['all'])
                                  for code in disease_codes(item)))
    if selection == 'all':
        return list(DISEASE_MAP)
    if selection == 'HPAI':
        return ['HPAI', 'HPAI_NON_POULTRY']
    if selection not in DISEASE_MAP:
        raise ValueError('지원하지 않는 질병입니다.')
    return [selection]


def load_presence_data(selection):
    codes = disease_codes(selection)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT countries.country, MAX(cr.region)
                FROM (
                    SELECT country COLLATE utf8mb4_unicode_ci AS country FROM country_regions
                    UNION
                    SELECT country COLLATE utf8mb4_unicode_ci FROM disease_reports
                ) countries
                LEFT JOIN country_regions cr
                  ON countries.country=cr.country COLLATE utf8mb4_unicode_ci
                WHERE countries.country IS NOT NULL AND countries.country<>''
                GROUP BY countries.country ORDER BY countries.country""")
            countries = cursor.fetchall()
            names = [DISEASE_MAP[code] for code in codes]
            cursor.execute(f"""SELECT DISTINCT TRIM(dr.disease),dr.country,
                    YEAR(o.start_date),MONTH(o.start_date)
                FROM disease_reports dr JOIN outbreaks o ON o.event_id=dr.event_id
                WHERE dr.disease IN ({', '.join(['%s'] * len(names))})
                  AND o.start_date IS NOT NULL""", names)
            rows = cursor.fetchall()
        name_to_code = {DISEASE_MAP[code].strip(): code for code in codes}
        facts = {code: set() for code in codes}
        for name, country, year, month in rows:
            facts[name_to_code[name]].add((country, int(year), int(month)))
        return countries, facts
    finally:
        conn.close()
