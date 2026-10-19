"""Control-measure snapshots in object storage; bounded-memory local SQL cache."""
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import Lock
import time

from woah import pdf_storage

CODES = ('ASF', 'BSE', 'FMD', 'HPAI', 'LSD')
HEADERS = ('Year', 'Semester', 'Region', 'Country / Territory', 'Disease',
           'Animal Category', 'Species', 'Control measure')
MANIFEST_KEY = 'wahis/control-measures/manifest.json'
_manifest = None
_manifest_until = 0
_lock = Lock()
_build_lock = Lock()
PAGE_SIZE = 8


def manifest():
    global _manifest, _manifest_until
    with _lock:
        if _manifest is not None and time.monotonic() < _manifest_until:
            return _manifest
        body = pdf_storage.client().get_object(Bucket=pdf_storage.bucket(), Key=MANIFEST_KEY)['Body']
        try:
            raw = body.read(1048577)
        finally:
            body.close()
        if len(raw) > 1048576:
            raise ValueError('Snapshot manifest is too large')
        result = json.loads(raw)
        if result.get('schema') != 1 or not result.get('files'):
            raise ValueError('Unsupported control-measures snapshot')
        for entry in result['files']:
            digest = entry['sha256']
            if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid snapshot digest')
            if entry['code'] not in CODES or entry['key'] != f'wahis/control-measures/{digest}.csv.gz':
                raise ValueError('Invalid snapshot object key')
        _manifest, _manifest_until = result, time.monotonic() + 60
        return result


def populate(conn, entries, fetch):
    """Stream CSV batches into SQLite; preserve every original row and column."""
    conn.execute('CREATE TABLE measures (year INTEGER,semester TEXT,region TEXT,country TEXT,disease TEXT,category TEXT,species TEXT,measure TEXT)')
    total = 0
    for entry in entries:
        with fetch(entry) as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != HEADERS:
                raise ValueError('Unexpected CSV columns')
            batch, count = [], 0
            for row in reader:
                if None in row or any(row[name] is None for name in HEADERS):
                    raise ValueError('Malformed control-measures row')
                batch.append((int(row[HEADERS[0]]), *(row[name] for name in HEADERS[1:])))
                count += 1
                if len(batch) == 1000:
                    conn.executemany('INSERT INTO measures VALUES (?,?,?,?,?,?,?,?)', batch)
                    batch.clear()
            if batch:
                conn.executemany('INSERT INTO measures VALUES (?,?,?,?,?,?,?,?)', batch)
            if count != entry['rows']:
                raise ValueError('Snapshot row count mismatch')
            total += count
    conn.execute('CREATE INDEX period_country ON measures(year,country)')
    conn.commit()
    return total


def local_snapshot(code, current):
    entries = [e for e in current['files'] if e['code'] == code]
    if not entries:
        raise ValueError('해당 질병의 방역 조치 자료가 없습니다.')
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    cache = Path(tempfile.gettempdir()) / 'wahis-control-cache'
    cache.mkdir(exist_ok=True)
    target = cache / f'{code}-{digest}.sqlite'
    with _build_lock:
        if target.exists():
            return target
        s3 = pdf_storage.client()

        def fetch(entry):
            # Download and hash compressed bytes before parsing. One source at a time.
            stream = tempfile.TemporaryFile()
            body = s3.get_object(Bucket=pdf_storage.bucket(), Key=entry['key'])['Body']
            h, size = hashlib.sha256(), 0
            try:
                for chunk in body.iter_chunks(chunk_size=65536):
                    size += len(chunk)
                    if size > entry['bytes']:
                        raise ValueError('Snapshot size exceeded manifest')
                    h.update(chunk)
                    stream.write(chunk)
                if size != entry['bytes'] or h.hexdigest() != entry['sha256']:
                    raise ValueError('Snapshot checksum mismatch')
                stream.seek(0)
            except Exception:
                stream.close()
                raise
            finally:
                body.close()
            return _CsvStream(stream)

        handle, name = tempfile.mkstemp(suffix='.sqlite', dir=cache)
        os.close(handle)
        tmp = Path(name)
        try:
            conn = sqlite3.connect(tmp)
            try:
                conn.execute('PRAGMA cache_size=-4096')
                populate(conn, entries, fetch)
            finally:
                conn.close()
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
        # Only current files are needed; active read connections can finish.
        for old in cache.glob(f'{code}-*.sqlite'):
            if old != target:
                try:
                    old.unlink()
                except OSError:
                    pass
    return target


class _CsvStream:
    def __init__(self, raw):
        self.raw = raw
        self.text = io.TextIOWrapper(gzip.GzipFile(fileobj=raw), encoding='utf-8-sig', newline='')

    def __enter__(self):
        return self.text

    def __exit__(self, *args):
        try:
            self.text.close()
        finally:
            self.raw.close()


def query(filters, page=0, page_size=PAGE_SIZE):
    code = filters.get('disease', 'HPAI')
    if code not in CODES:
        raise ValueError('지원하지 않는 질병입니다.')
    current = manifest()
    path = local_snapshot(code, current)
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return query_rows(conn, filters, page, current.get('snapshot_at'), page_size)
    finally:
        conn.close()


def query_rows(conn, filters, page=0, snapshot_at=None, page_size=PAGE_SIZE):
    page_size = max(1, min(int(page_size), 100))
    where, args = ['1=1'], []
    year = filters.get('year', 'all')
    if year != 'all':
        where.append('year=?')
        args.append(int(year))
    semester = filters.get('semester', 'all')
    if semester in ('1', '2'):
        where.append('semester LIKE ?')
        args.append('Jan-Jun%' if semester == '1' else 'Jul-Dec%')
    country = filters.get('country', '').strip()
    if country:
        where.append("country LIKE ? ESCAPE '\\'")
        args.append('%' + country.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
    scope = filters.get('scope', 'all')
    if scope == 'vaccination':
        where.append("measure IN ('Official vaccination','Vaccination prohibited')")
    elif scope == 'official':
        where.append("measure='Official vaccination'")
    condition = ' AND '.join(where)
    count = conn.execute('SELECT COUNT(*) FROM measures WHERE ' + condition, args).fetchone()[0]
    page = max(0, min(int(page), max(0, (count - 1) // page_size)))
    rows = conn.execute('SELECT * FROM measures WHERE ' + condition +
                        ' ORDER BY year DESC,semester DESC,country,disease,species,measure,region,category LIMIT ? OFFSET ?',
                        [*args, page_size, page * page_size]).fetchall()
    return {'rows': [dict(row) for row in rows], 'total': count, 'page': page, 'snapshot_at': snapshot_at}
