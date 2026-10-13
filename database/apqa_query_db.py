
from datetime import datetime, timezone

from database.db import get_connection


def get_apqa_snapshot():
    """APQA 수입허용, 수입제한 및 마지막 수집 시각 조회"""

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            cursor.execute("""
                SELECT category, product, country,
                       country_raw, status
                FROM apqa_import_permissions
                WHERE status = 'ACTIVE'
            """)

            permission_columns = [
                "category", "product", "country",
                "country_raw", "status"
            ]

            permissions = [
                dict(zip(permission_columns, row))
                for row in cursor.fetchall()
            ]

            cursor.execute("""
                SELECT disease_code, source_disease_group,
                       product, country, country_raw,
                       scope, effective_date, lifted_date,
                       status
                FROM apqa_import_restrictions
                WHERE status IN ('ACTIVE', 'REVIEW')
            """)

            restriction_columns = [
                "disease_code", "source_disease_group",
                "product", "country", "country_raw",
                "scope", "effective_date", "lifted_date",
                "status"
            ]

            restrictions = [
                dict(zip(restriction_columns, row))
                for row in cursor.fetchall()
            ]

            cursor.execute("""
                SELECT completed_at
                FROM apqa_collection_logs
                WHERE status = 'SUCCESS'
                ORDER BY completed_at DESC
                LIMIT 1
            """)

            row = cursor.fetchone()
            last_sync = row[0] if row else None

        age_hours = None

        if last_sync:
            age_hours = (
                datetime.now(timezone.utc)
                - last_sync.replace(tzinfo=timezone.utc)
            ).total_seconds() / 3600

        return {
            "permissions": permissions,
            "restrictions": restrictions,
            "last_sync": last_sync,
            "age_hours": age_hours
        }

    finally:
        conn.close()
