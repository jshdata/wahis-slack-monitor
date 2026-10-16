"""QIA No2 import case counts; export and rejection data are never included."""
from datetime import date

from database.db import get_connection

START_MONTH = date(2020, 1, 1)


def month_range(latest):
    current = START_MONTH
    while current <= latest:
        yield current
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)


def load_import_options():
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""SELECT DISTINCT product_category, product_name
                FROM qia_trade_statistics
                WHERE statistics_type IN (3,4) AND reference_month >= %s
                ORDER BY product_category, product_name""", (START_MONTH,))
            products = list(cursor.fetchall())
            cursor.execute("""SELECT DISTINCT country_name FROM qia_trade_statistics
                WHERE statistics_type IN (3,4) AND reference_month >= %s
                ORDER BY country_name""", (START_MONTH,))
            countries = [r[0] for r in cursor.fetchall()]
        return {"category": sorted({r[0] for r in products}),
                "product": products, "country": countries}
    finally:
        connection.close()


def load_import_counts(categories=(), products=(), countries=()):
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""SELECT reference_month, statistics_type
                FROM qia_statistics_collections
                WHERE source_no=2 AND statistics_type IN (3,4)
                  AND status='COMPLETE' AND reference_month >= %s
                ORDER BY reference_month, statistics_type""", (START_MONTH,))
            coverage = {(r[0], int(r[1])) for r in cursor.fetchall()}
            if not coverage:
                raise ValueError("저장된 수입 통계가 없습니다.")
            latest = max(month for month, _ in coverage)
            missing = [(month, t) for month in month_range(latest) for t in (3, 4)
                       if (month, t) not in coverage]
            if missing:
                raise ValueError("수입 통계에 미수집 월이 있습니다. 자료 수집을 완료한 뒤 다시 조회해주세요.")
            conditions = ["statistics_type IN (3,4)", "reference_month >= %s", "reference_month <= %s"]
            params = [START_MONTH, latest]
            for column, values in (("product_category", categories), ("product_name", products),
                                   ("country_name", countries)):
                values = list(dict.fromkeys(values))
                if values:
                    conditions.append(f"{column} IN ({','.join(['%s'] * len(values))})")
                    params.extend(values)
            cursor.execute(f"""SELECT product_category, product_name, country_name,
                    reference_month, SUM(case_count)
                FROM qia_trade_statistics WHERE {' AND '.join(conditions)}
                GROUP BY product_category, product_name, country_name, reference_month
                ORDER BY product_category, product_name, country_name, reference_month""", params)
            rows = [(category, product, country, month, int(count))
                    for category, product, country, month, count in cursor.fetchall()]
        return {"latest_month": latest, "rows": rows}
    finally:
        connection.close()
