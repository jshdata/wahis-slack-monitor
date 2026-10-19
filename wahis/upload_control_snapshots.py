"""Publish verified, compressed control-measure CSV snapshots to the existing bucket."""
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

from dotenv import load_dotenv
from wahis.control_storage import HEADERS, MANIFEST_KEY, CODES
from woah import pdf_storage


def upload(directory):
    source = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    result = {'schema': 1, 'snapshot_at': source['downloads_completed_at'], 'files': []}
    s3 = pdf_storage.client()
    for entry in source['files']:
        path = directory / entry['file'].replace('\\', '/').split('/')[-1]
        raw = path.read_bytes()
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
        if tuple(reader.fieldnames or ()) != HEADERS or entry['code'] not in CODES:
            raise ValueError('Invalid source CSV')
        rows = sum(1 for row in reader)
        if rows != entry['rows'] or len(raw) != entry['bytes']:
            raise ValueError('Source CSV size/row mismatch')
        original_hash = hashlib.sha256(raw).hexdigest()
        expected_hash = entry.get('import', {}).get('source_sha256')
        if expected_hash and original_hash != expected_hash:
            raise ValueError('Source CSV hash mismatch')
        data = gzip.compress(raw, mtime=0)
        digest = hashlib.sha256(data).hexdigest()
        key = f'wahis/control-measures/{digest}.csv.gz'
        s3.put_object(Bucket=pdf_storage.bucket(), Key=key, Body=data, ContentType='application/gzip')
        body = s3.get_object(Bucket=pdf_storage.bucket(), Key=key)['Body']
        try:
            downloaded = body.read()
        finally:
            body.close()
        if hashlib.sha256(downloaded).hexdigest() != digest or gzip.decompress(downloaded) != raw:
            raise ValueError('Upload verification failed')
        result['files'].append({'code': entry['code'], 'disease': entry['disease'],
                                'rows': rows, 'bytes': len(data), 'sha256': digest,
                                'source_sha256': original_hash, 'key': key})
        print(json.dumps({'file': path.name, 'rows': rows, 'compressed_bytes': len(data), 'verified': True}), flush=True)
    # Publish the pointer only after every file has passed verification.
    payload = json.dumps(result, ensure_ascii=False).encode()
    s3.put_object(Bucket=pdf_storage.bucket(), Key=MANIFEST_KEY, Body=payload, ContentType='application/json')
    body = s3.get_object(Bucket=pdf_storage.bucket(), Key=MANIFEST_KEY)['Body']
    try:
        if body.read() != payload:
            raise ValueError('Manifest verification failed')
    finally:
        body.close()
    (directory / 'bucket_upload_result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'total_rows': sum(e['rows'] for e in result['files']),
                      'total_compressed_bytes': sum(e['bytes'] for e in result['files'])}), flush=True)


if __name__ == '__main__':
    load_dotenv('.env')
    upload(Path('data/control_measures_global'))
