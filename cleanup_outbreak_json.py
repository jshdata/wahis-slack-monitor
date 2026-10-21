"""Back up outbreak JSON locally, then remove only redundant DB JSON storage.

Stop all outbreak loaders before running. Does not delete species/category rows.
"""
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from database.db import get_connection


def main():
    directory = Path(__file__).resolve().parent / 'data' / 'outbreak_json_backup'
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SET SESSION lock_wait_timeout=10')
            cur.execute('SHOW COLUMNS FROM outbreak_species')
            has_raw = any(row[0] == 'raw_json' for row in cur.fetchall())
            cur.execute("SHOW TABLES LIKE 'outbreak_detail_snapshots'")
            has_snapshots = cur.fetchone() is not None
            cur.execute('SELECT COUNT(*) FROM outbreak_species')
            species_before = cur.fetchone()[0]
            targets = []
            if has_raw:
                targets.append('outbreak_species')
            if has_snapshots:
                targets.append('outbreak_detail_snapshots')
            # Finish and verify all backups before either destructive statement.
            for table in targets:
                path = directory / f'{stamp}_{table}.jsonl.gz'
                cur.execute('SELECT * FROM ' + table)
                names = [column[0] for column in cur.description]
                count = 0
                with gzip.open(path, 'xt', encoding='utf-8') as stream:
                    while True:
                        rows = cur.fetchmany(500)
                        if not rows:
                            break
                        for row in rows:
                            stream.write(json.dumps(dict(zip(names, row)),
                                                    ensure_ascii=False, default=str) + '\n')
                            count += 1
                with gzip.open(path, 'rt', encoding='utf-8') as stream:
                    verified = sum(1 for line in stream if isinstance(json.loads(line), dict))
                if verified != count:
                    raise ValueError('Backup verification failed; DB cleanup cancelled')
                print(f'Backup verified: {table} rows={count} bytes={path.stat().st_size} path={path}', flush=True)
            if has_raw:
                cur.execute('ALTER TABLE outbreak_species DROP COLUMN raw_json')
                print('Removed outbreak_species.raw_json', flush=True)
            if has_snapshots:
                cur.execute('DROP TABLE outbreak_detail_snapshots')
                print('Removed outbreak_detail_snapshots', flush=True)
            cur.execute('SELECT COUNT(*) FROM outbreak_species')
            if cur.fetchone()[0] != species_before:
                raise ValueError('Species row count changed; check concurrent loaders')
            print(f'Preserved species rows: {species_before}. Category/completion columns unchanged.', flush=True)
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    main()
