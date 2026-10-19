"""Private, content-addressed PDF storage in Railway or Cloudflare R2."""
import hashlib
import os
from urllib.parse import urlparse


def enabled():
    provider = os.getenv('WOAH_PDF_STORAGE', 'mysql').lower()
    if provider not in ('mysql', 'r2', 'railway'):
        raise ValueError('WOAH_PDF_STORAGE must be mysql, r2, or railway')
    return provider != 'mysql'


def prefix():
    return 'S3' if os.getenv('WOAH_PDF_STORAGE', 'mysql').lower() == 'railway' else 'R2'


def bucket():
    return os.environ[prefix() + '_BUCKET']


def client():
    import boto3
    base = prefix()
    names = tuple(base + '_' + suffix for suffix in
                  ('ENDPOINT_URL', 'BUCKET', 'ACCESS_KEY_ID', 'SECRET_ACCESS_KEY'))
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise ValueError('Missing object storage settings: ' + ', '.join(missing))
    endpoint = os.environ[base + '_ENDPOINT_URL']
    parsed = urlparse(endpoint)
    host = parsed.hostname or ''
    allowed = (host == 'storage.railway.app' or host.endswith('.storage.railway.app')
               or host.endswith('.storageapi.dev')) if base == 'S3' else host.endswith('.r2.cloudflarestorage.com')
    if (parsed.scheme != 'https' or not parsed.hostname or
            not allowed or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('Invalid HTTPS object storage endpoint for selected provider')
    style = os.getenv('S3_ADDRESSING_STYLE', 'virtual') if base == 'S3' else 'auto'
    if style not in ('auto', 'virtual', 'path'):
        raise ValueError('S3_ADDRESSING_STYLE must be auto, virtual, or path')
    from botocore.config import Config
    return boto3.client(
        's3', endpoint_url=endpoint, region_name=os.getenv(base + '_REGION', 'auto'),
        aws_access_key_id=os.environ[base + '_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ[base + '_SECRET_ACCESS_KEY'],
        config=Config(connect_timeout=10, read_timeout=60, s3={'addressing_style': style},
                      retries={'max_attempts': 3, 'mode': 'standard'}))


def key(digest):
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid PDF SHA-256')
    return f'woah/pdf/{digest}.pdf'


def read_pdf(digest):
    response = client().get_object(Bucket=bucket(), Key=key(digest))
    body = response['Body']
    try:
        pdf = body.read()
    finally:
        body.close()
    if hashlib.sha256(pdf).hexdigest() != digest:
        raise ValueError('Object storage PDF checksum mismatch')
    return pdf


def store_pdf(pdf):
    digest = hashlib.sha256(pdf).hexdigest()
    client().put_object(Bucket=bucket(), Key=key(digest),
                        Body=pdf, ContentType='application/pdf')
    # Verify a complete round trip before any database reference is changed.
    if read_pdf(digest) != pdf:
        raise ValueError('Object storage PDF verification failed')
    return digest
