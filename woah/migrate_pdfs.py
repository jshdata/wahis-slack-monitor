"""Run as python -m woah.migrate_pdfs; default only uploads and verifies."""
import argparse
import time
import pymysql

from database.woah_db import connection
from woah import pdf_storage


def read_version(version_id):
    from database.db import get_connection
    for attempt in range(3):
        conn = None
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute('SELECT sha256,pdf_data FROM woah_document_versions WHERE id=%s', (version_id,))
                return cur.fetchone()
        except (pymysql.OperationalError, pymysql.InterfaceError):
            if attempt == 2:
                raise
            time.sleep(2)
        finally:
            if conn:
                conn.close()


def migrate(remove_db_copies=False, start_id=0):
    # Snapshot IDs, then fetch one PDF at a time rather than all blobs at once.
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT id FROM woah_document_versions ORDER BY id')
        ids = [row[0] for row in cur.fetchall()]
    for version_id in ids:
        if version_id < start_id:
            continue
        row = read_version(version_id)
        if not row:
            continue
        digest, pdf = row
        if pdf:
            import hashlib
            if hashlib.sha256(pdf).hexdigest() != digest:
                raise ValueError(f'Database checksum mismatch for version {version_id}')
            pdf_storage.store_pdf(pdf)
        else:
            pdf_storage.read_pdf(digest)
        if remove_db_copies and pdf:
            with connection() as conn, conn.cursor() as cur:
                cur.execute("UPDATE woah_document_versions SET pdf_data=%s WHERE id=%s AND sha256=%s",
                            (b'', version_id, digest))
        print(f'Version {version_id}: verified' + ('; DB copy removed' if remove_db_copies and pdf else ''))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-id', type=int, default=0, help='Resume from this version ID')
    parser.add_argument('--remove-db-copies', action='store_true',
                        help='Only after all readers/writers deploy object storage support and credentials')
    args = parser.parse_args()
    migrate(args.remove_db_copies, args.start_id)
