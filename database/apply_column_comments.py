"""Apply Korean column comments while preserving live column definitions.

Preview: python -m database.apply_column_comments
Apply:   python -m database.apply_column_comments --apply
"""
import argparse
import json
import re
from pathlib import Path

from database.db import get_connection

SCHEMA_QUERY = '''SELECT table_name,column_name,ordinal_position,column_default,
 is_nullable,data_type,column_type,character_set_name,collation_name,extra,
 column_key,generation_expression
 FROM information_schema.columns WHERE table_schema=DATABASE()
 ORDER BY table_name,ordinal_position'''
INDEX_QUERY = '''SELECT table_name,index_name,non_unique,seq_in_index,column_name,
 collation,sub_part,index_type,expression
 FROM information_schema.statistics WHERE table_schema=DATABASE()
 ORDER BY table_name,index_name,seq_in_index'''
KEY_QUERY = '''SELECT table_name,constraint_name,column_name,ordinal_position,
 referenced_table_schema,referenced_table_name,referenced_column_name
 FROM information_schema.key_column_usage WHERE table_schema=DATABASE()
 ORDER BY table_name,constraint_name,ordinal_position'''


def apply_comments(apply=False):
    spec = json.loads(Path(__file__).with_name('column_comments_ko.json').read_text(encoding='utf-8'))
    out = Path('data/column_comments')
    out.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SET SESSION lock_wait_timeout=10')
            # ANSI mode makes SHOW CREATE omit table options and use double quotes.
            # Adjust this maintenance connection only so full definitions are retained.
            cur.execute('SELECT @@session.sql_mode')
            modes = cur.fetchone()[0].split(',')
            omitted = {'ANSI', 'ANSI_QUOTES', 'NO_FIELD_OPTIONS', 'NO_KEY_OPTIONS', 'NO_TABLE_OPTIONS'}
            cur.execute('SET SESSION sql_mode=%s', (','.join(mode for mode in modes if mode not in omitted),))
            cur.execute(SCHEMA_QUERY)
            before = cur.fetchall()
            cur.execute(INDEX_QUERY)
            indexes = cur.fetchall()
            cur.execute(KEY_QUERY)
            keys = cur.fetchall()
            cur.execute('SELECT table_name,table_comment FROM information_schema.tables '
                        'WHERE table_schema=DATABASE() ORDER BY table_name')
            table_comments = cur.fetchall()
            if {row[0] for row in before} != set(spec['tables']):
                raise ValueError('Table list differs from reviewed comment specification')
            expected = {}
            for table, column, *_ in before:
                comment = spec['tables'][table].get(column, spec['common'].get(column))
                if not comment:
                    raise ValueError(f'Missing description: {table}.{column}')
                expected[(table, column)] = comment
            statements, rollback, original = [], [], {}
            for table in spec['tables']:
                if not re.fullmatch(r'[a-z_]+', table):
                    raise ValueError('Unexpected table identifier')
                cur.execute(f'SHOW CREATE TABLE `{table}`')
                ddl = cur.fetchone()[1]
                original[table] = ddl
                changes, restore = [], []
                for line in ddl.splitlines():
                    match = re.match(r'^  `([a-z][a-z0-9_]*)` (.*?)(?:,)?$', line)
                    if not match:
                        continue
                    column, definition = match.groups()
                    # Keep type, collation, NULL/default, auto increment and ON UPDATE
                    # exactly as SHOW CREATE TABLE reports them.
                    clean = re.sub(r" COMMENT '(?:[^'\\]|\\.|'')*'", '', definition)
                    changes.append(f'MODIFY COLUMN `{column}` {clean} COMMENT {conn.escape(expected[(table, column)])}')
                    restore.append(f'MODIFY COLUMN `{column}` {definition}')
                if len(changes) != sum(1 for row in before if row[0] == table):
                    raise ValueError(f'Column definition parsing mismatch: {table}')
                # Refuse a table-copy fallback; column comments only need metadata changes.
                statements.append(f'ALTER TABLE `{table}` ' + ',\n  '.join(changes)
                                  + ', ALGORITHM=INPLACE, LOCK=NONE;')
                rollback.append(f'ALTER TABLE `{table}` ' + ',\n  '.join(restore)
                                + ', ALGORITHM=INPLACE, LOCK=NONE;')
            (out / 'schema_before.json').write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding='utf-8')
            (out / 'apply.sql').write_text('\n\n'.join(statements) + '\n', encoding='utf-8')
            (out / 'rollback.sql').write_text('\n\n'.join(rollback) + '\n', encoding='utf-8')
            print('PREPARED', len(statements), 'tables', len(expected), 'column comments', flush=True)
            if not apply:
                return
            for table, sql in zip(spec['tables'], statements):
                cur.execute(sql)
                print('COMMENTED', table, flush=True)
            for query, expected_schema, label in ((SCHEMA_QUERY, before, 'column definitions'),
                                                   (INDEX_QUERY, indexes, 'indexes'),
                                                   (KEY_QUERY, keys, 'keys')):
                cur.execute(query)
                if cur.fetchall() != expected_schema:
                    raise ValueError(f'Unexpected change in {label}')
            cur.execute('SELECT table_name,table_comment FROM information_schema.tables '
                        'WHERE table_schema=DATABASE() ORDER BY table_name')
            if cur.fetchall() != table_comments:
                raise ValueError('Table comments changed unexpectedly')
            cur.execute('SELECT table_name,column_name,column_comment FROM information_schema.columns '
                        'WHERE table_schema=DATABASE()')
            actual = {(table, column): comment for table, column, comment in cur.fetchall()}
            if actual != expected:
                raise ValueError('Column comment verification failed')
            print('VERIFIED', len(expected), 'Korean comments; definitions and keys unchanged', flush=True)
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    apply_comments(parser.parse_args().apply)
