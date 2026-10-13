"""APQA import-permission and restriction snapshot synchronization for Aiven MySQL.

Run from project root via apqa_main.py (or this module for schema-only setup).
Requires existing database.db.get_connection().
"""
import hashlib
import json
from datetime import datetime, timezone

import os
import sys

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database.db import get_connection

SOURCE_URL = 'https://www.apqa.go.kr/livestock/clean/listwebQiaCom.do?type=91_103xxtFN&clear=1'

DDL = [
    """CREATE TABLE IF NOT EXISTS apqa_import_permissions (
        record_key CHAR(64) PRIMARY KEY,
        category VARCHAR(40) NOT NULL,
        product TEXT NOT NULL,
        country VARCHAR(150) NOT NULL,
        country_raw TEXT NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
        first_seen_at DATETIME NOT NULL,
        last_seen_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        INDEX idx_permission_country (country),
        INDEX idx_permission_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS apqa_import_restrictions (
        record_key CHAR(64) PRIMARY KEY,
        disease_code VARCHAR(30) NOT NULL,
        source_disease_group VARCHAR(30) NOT NULL,
        product TEXT NOT NULL,
        country VARCHAR(150) NOT NULL,
        country_raw TEXT NOT NULL,
        scope VARCHAR(16) NOT NULL,
        effective_date DATE NULL,
        lifted_date DATE NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
        first_seen_at DATETIME NOT NULL,
        last_seen_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        INDEX idx_restriction_lookup (country, disease_code, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS apqa_import_history (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        collection_id BIGINT NOT NULL,
        dataset VARCHAR(20) NOT NULL,
        record_key CHAR(64) NOT NULL,
        action VARCHAR(20) NOT NULL,
        before_data JSON NULL,
        after_data JSON NULL,
        changed_at DATETIME NOT NULL,
        INDEX idx_history_collection (collection_id),
        INDEX idx_history_key (record_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS apqa_collection_logs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        checked_at DATETIME NOT NULL,
        completed_at DATETIME NULL,
        status VARCHAR(16) NOT NULL,
        permission_count INT NOT NULL DEFAULT 0,
        restriction_count INT NOT NULL DEFAULT 0,
        inserted_count INT NOT NULL DEFAULT 0,
        updated_count INT NOT NULL DEFAULT 0,
        review_count INT NOT NULL DEFAULT 0,
        removed_count INT NOT NULL DEFAULT 0,
        error_message TEXT NULL,
        source_url TEXT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
]

PERMISSION_FIELDS = ('category', 'product', 'country', 'country_raw')
RESTRICTION_FIELDS = ('disease_code', 'source_disease_group', 'product', 'country', 'country_raw', 'scope', 'effective_date', 'lifted_date')


def _key(parts):
    raw = json.dumps(parts, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _normalize(record, fields):
    return {name: record.get(name) for name in fields}



def _prepare_permissions(rows):
    output = {}
    duplicate_count = 0

    for item in rows:
        data = _normalize(item, PERMISSION_FIELDS)

        if not all(data.values()):
            raise ValueError(
                f"Incomplete permission record: {data}"
            )

        key = _key([
            data["category"],
            data["product"],
            data["country_raw"]
        ])

        if key in output:
            # 완전히 동일한 데이터라면 중복 제거
            if output[key] == data:
                duplicate_count += 1
                continue

            # 동일한 식별자인데 내용이 다르면 오류
            raise ValueError(
                f"Conflicting permission record: {data}"
            )

        output[key] = data

    print(f"수입허용 원본 레코드: {len(rows)}건")
    print(f"중복 제거: {duplicate_count}건")
    print(f"수입허용 최종 레코드: {len(output)}건")

    return output



def _prepare_restrictions(rows):
    output = {}
    for item in rows:
        data = _normalize(item, RESTRICTION_FIELDS)
        if not all(data[k] for k in ('disease_code', 'source_disease_group', 'product', 'country', 'country_raw', 'scope', 'effective_date')):
            raise ValueError(f'Incomplete restriction record: {data}')
        if data['scope'] not in ('FULL', 'PARTIAL'):
            raise ValueError(f'Unexpected restriction scope: {data}')
        # Scope/date are values, not identity; changes generate UPDATE history.
        key = _key([data['disease_code'], data['product'], data['country_raw']])
        if key in output:
            raise ValueError(f'Duplicate restriction record: {data}')
        output[key] = data
    return output


def init_apqa_tables():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            for statement in DDL:
                cursor.execute(statement)
        conn.commit()
    finally:
        conn.close()


def _existing(cursor, table, fields):
    cursor.execute(f"SELECT record_key, {', '.join(fields)}, status FROM {table}")
    result = {}
    for row in cursor.fetchall():
        key, *values = row
        status = values.pop()
        data = dict(zip(fields, values))
        for date_field in ('effective_date', 'lifted_date'):
            if data.get(date_field) is not None:
                data[date_field] = data[date_field].isoformat()
        result[key] = (data, status)
    return result


def _history(cursor, log_id, dataset, key, action, before, after, now):
    cursor.execute(
        """INSERT INTO apqa_import_history
           (collection_id, dataset, record_key, action, before_data, after_data, changed_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (log_id, dataset, key, action,
         json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
         json.dumps(after, ensure_ascii=False, default=str) if after is not None else None, now)
    )


def _sync_dataset(cursor, log_id, dataset, table, fields, incoming, now):
    existing = _existing(cursor, table, fields)
    counts = {'inserted': 0, 'updated': 0, 'review': 0, 'removed': 0}
    for key, data in incoming.items():
        old = existing.get(key)
        if old is None:
            cols = ('record_key',) + fields + ('status', 'first_seen_at', 'last_seen_at', 'updated_at')
            cursor.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                (key,) + tuple(data[f] for f in fields) + ('ACTIVE', now, now, now)
            )
            _history(cursor, log_id, dataset, key, 'INSERT', None, data, now)
            counts['inserted'] += 1
        else:
            old_data, old_status = old
            if old_data != data or old_status != 'ACTIVE':
                assignments = ', '.join(f'{f}=%s' for f in fields)
                cursor.execute(
                    f"UPDATE {table} SET {assignments}, status='ACTIVE', last_seen_at=%s, updated_at=%s WHERE record_key=%s",
                    tuple(data[f] for f in fields) + (now, now, key)
                )
                _history(cursor, log_id, dataset, key, 'UPDATE' if old_status == 'ACTIVE' else 'REAPPEARED',
                         {**old_data, 'status': old_status}, {**data, 'status': 'ACTIVE'}, now)
                counts['updated'] += 1
            else:
                cursor.execute(f'UPDATE {table} SET last_seen_at=%s WHERE record_key=%s', (now, key))

    for key, (old_data, old_status) in existing.items():
        if key in incoming:
            continue
        if dataset == 'PERMISSION' and old_status == 'ACTIVE':
            new_status = 'REMOVED'
            counts['removed'] += 1
        elif dataset == 'RESTRICTION' and old_status == 'ACTIVE':
            new_status = 'REVIEW'
            counts['review'] += 1
        else:
            continue
        cursor.execute(f'UPDATE {table} SET status=%s, updated_at=%s WHERE record_key=%s',
                       (new_status, now, key))
        _history(cursor, log_id, dataset, key, new_status, {**old_data, 'status': old_status},
                 {**old_data, 'status': new_status}, now)
    return counts


def sync_apqa_data(data, *, allow_large_removal=False):
    """Atomically synchronize validated parser output.

    First run requires at least 100 permission records and 20 restriction records.
    Subsequent runs reject sudden drops (>20%) by default, preventing destructive
    changes from partial HTML parsing. Override only after manual verification.
    """
    if not isinstance(data, dict):
        raise TypeError('data must be a dict returned by get_apqa_data()')
    permissions = _prepare_permissions(data.get('permissions', []))
    restrictions = _prepare_restrictions(data.get('restrictions', []))
    if len(permissions) < 100 or len(restrictions) < 20:
        raise ValueError(f'Unexpectedly few APQA records: {len(permissions)} permissions, {len(restrictions)} restrictions')

    init_apqa_tables()
    conn = get_connection()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM apqa_import_permissions WHERE status=%s', ('ACTIVE',))
            old_p = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM apqa_import_restrictions WHERE status=%s', ('ACTIVE',))
            old_r = cursor.fetchone()[0]
            if not allow_large_removal:
                if old_p and len(permissions) < old_p * 0.8:
                    raise ValueError(f'Permission record count dropped sharply: {old_p} -> {len(permissions)}')
                if old_r and len(restrictions) < old_r * 0.8:
                    raise ValueError(f'Restriction record count dropped sharply: {old_r} -> {len(restrictions)}')
            cursor.execute(
                """INSERT INTO apqa_collection_logs
                   (checked_at, status, permission_count, restriction_count, source_url)
                   VALUES (%s, 'RUNNING', %s, %s, %s)""",
                (now, len(permissions), len(restrictions), SOURCE_URL)
            )
            log_id = cursor.lastrowid
            p = _sync_dataset(cursor, log_id, 'PERMISSION', 'apqa_import_permissions', PERMISSION_FIELDS, permissions, now)
            r = _sync_dataset(cursor, log_id, 'RESTRICTION', 'apqa_import_restrictions', RESTRICTION_FIELDS, restrictions, now)
            totals = {name: p[name] + r[name] for name in p}
            cursor.execute(
                """UPDATE apqa_collection_logs SET status='SUCCESS', completed_at=%s,
                   inserted_count=%s, updated_count=%s, review_count=%s, removed_count=%s
                   WHERE id=%s""",
                (datetime.now(timezone.utc).replace(tzinfo=None), totals['inserted'], totals['updated'],
                 totals['review'], totals['removed'], log_id)
            )
        conn.commit()
        return {'collection_id': log_id, 'permissions': len(permissions), 'restrictions': len(restrictions), **totals}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    init_apqa_tables()
    print('APQA MySQL tables initialized successfully.')
