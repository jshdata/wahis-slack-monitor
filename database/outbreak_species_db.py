"""Resumable, version-aware storage of outbreak-level species."""

from database.db import get_connection


def ensure_schema():
    """Explicitly invoked by --init-schema; safe to repeat after interruption."""
    print('Schema: connecting to DB...', flush=True)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            print('Schema: checking outbreaks columns...', flush=True)
            cur.execute("SHOW COLUMNS FROM outbreaks")
            columns = {row[0] for row in cur.fetchall()}
            additions = {
                'animal_category': "VARCHAR(16) NOT NULL DEFAULT 'unknown'",
                'species_loaded_report_id': 'INT NULL',
                'species_loaded_at': 'DATETIME NULL',
            }
            for name, definition in additions.items():
                if name not in columns:
                    print(f'Schema: adding outbreaks.{name} (may wait for a table lock)...', flush=True)
                    cur.execute(f'ALTER TABLE outbreaks ADD COLUMN {name} {definition}')
                    print(f'Schema: added {name}.', flush=True)
            print('Schema: ensuring outbreak_species table...', flush=True)
            cur.execute('''CREATE TABLE IF NOT EXISTS outbreak_species (
                outbreak_id INT NOT NULL,
                row_index INT NOT NULL,
                report_id INT NOT NULL,
                species_id INT NULL,
                species_name VARCHAR(255) NULL,
                is_wild TINYINT(1) NULL,
                PRIMARY KEY (outbreak_id, row_index),
                KEY idx_outbreak_species_species (species_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')
        conn.commit()
    finally:
        conn.close()


PENDING = """FROM outbreaks
    WHERE COALESCE(last_update_report_id, created_by_report_id) IS NOT NULL
      AND (species_loaded_report_id IS NULL OR
           species_loaded_report_id <> COALESCE(last_update_report_id, created_by_report_id))"""


def get_pending(after_id=0, limit=100):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT outbreak_id, COALESCE(last_update_report_id, created_by_report_id) '
                        + PENDING + ' AND outbreak_id > %s ORDER BY outbreak_id LIMIT %s',
                        (after_id, limit))
            return cur.fetchall()
    finally:
        conn.close()


def get_remaining_count():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) ' + PENDING)
            return cur.fetchone()[0]
    finally:
        conn.close()


def get_pending_for_outbreaks(outbreak_ids):
    """Read current versions, so historical report retries never downgrade data."""
    ids = sorted(set(outbreak_ids))
    if not ids:
        return []
    conn = get_connection()
    try:
        result = []
        with conn.cursor() as cur:
            for offset in range(0, len(ids), 500):
                batch = ids[offset:offset + 500]
                placeholders = ','.join(['%s'] * len(batch))
                cur.execute('SELECT outbreak_id, COALESCE(last_update_report_id, created_by_report_id) '
                            + PENDING + f' AND outbreak_id IN ({placeholders}) ORDER BY outbreak_id',
                            tuple(batch))
                result.extend(cur.fetchall())
        return result
    finally:
        conn.close()


def parse_species(data, outbreak_id):
    if not isinstance(data, dict) or (data.get('outbreak') or {}).get('outbreakId') != outbreak_id:
        raise ValueError('Outbreak response ID mismatch or malformed response')
    items = data.get('speciesQuantities')
    if not isinstance(items, list):
        raise ValueError('Missing speciesQuantities list; leave outbreak pending')
    rows, flags = [], []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get('totalQuantities'), dict):
            raise ValueError('Malformed totalQuantities; leave outbreak pending')
        qty = item['totalQuantities']
        flag = qty.get('isWild')
        if flag is not None and type(flag) is not bool:
            raise ValueError('isWild must be boolean or null')
        flags.append(flag)
        rows.append((outbreak_id, index, qty.get('speciesId'), qty.get('speciesName'),
                     flag))
    known = {flag for flag in flags if flag is not None}
    if known == {True, False}:
        category = 'mixed'
    elif not flags or None in flags:
        category = 'unknown'
    else:
        category = 'wild' if True in known else 'domestic'
    return rows, category


def save_outbreak_species(outbreak_id, report_id, data, connection=None):
    rows, category = parse_species(data, outbreak_id)
    conn = connection if connection is not None else get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT COALESCE(last_update_report_id, created_by_report_id) '
                        'FROM outbreaks WHERE outbreak_id=%s FOR UPDATE', (outbreak_id,))
            current = cur.fetchone()
            if not current or current[0] != report_id:
                raise ValueError('Outbreak report version changed; retry on next run')
            cur.execute('DELETE FROM outbreak_species WHERE outbreak_id=%s', (outbreak_id,))
            if rows:
                cur.executemany('''INSERT INTO outbreak_species
                    (outbreak_id,row_index,report_id,species_id,species_name,is_wild)
                    VALUES (%s,%s,%s,%s,%s,%s)''',
                    [(oid, idx, report_id, sid, name, wild)
                     for oid, idx, sid, name, wild in rows])
            cur.execute('''UPDATE outbreaks SET animal_category=%s,
                species_loaded_report_id=%s, species_loaded_at=UTC_TIMESTAMP()
                WHERE outbreak_id=%s''', (category, report_id, outbreak_id))
        conn.commit()
        return category
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        if connection is None:
            conn.close()
