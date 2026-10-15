"""Read the public Power BI table, including English document URLs.

Fail closed when the table is incomplete or its schema changes. Never infer
disease freedom, a revoked declaration, or a missing PDF from a network error.
"""
import io
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pypdf import PdfReader

SOURCE_URL = 'https://www.woah.org/en/what-we-offer/self-declared-disease-status/'
# Public report linked by SOURCE_URL. Override if WOAH replaces the report.
REPORT_URL = ('https://app.powerbi.com/view?r='
              'eyJrIjoiMGU5MDEyMzYtZDY3MS00YTNhLWE5YzctNDdlZWQ2ZmEzNzIwIiwidCI6ImYxZmFmNTYzLWIwNmQtNGMzNS04NzM5LTM0Y2NjMjgwZGNhZiIsImMiOjh9')
DISEASES = {
    'ASF': 'African swine fever',
    'HPAI': 'High pathogenicity avian influenza',
    'FMD': 'Foot and mouth disease',
    'LSD': 'Lumpy skin disease',
}


def disease_code(name):
    normalized = re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip()
    for code, label in DISEASES.items():
        if re.sub(r'[^a-z0-9]+', ' ', label.lower()).strip() in normalized:
            return code
    return None


def decode_table(data):
    """Decode Power BI dictionary values, repeat/null bitmasks and raw cells."""
    selects = data.get('descriptor', {}).get('Select', [])
    if not any('Link_EN' in col.get('Name', '') for col in selects):
        return None  # slicer queries are not document lists
    datasets = data.get('dsr', {}).get('DS', [])
    if len(datasets) != 1 or datasets[0].get('IC') is not True:
        raise ValueError('WOAH table is incomplete; collection was not accepted')
    dataset = datasets[0]
    dictionaries = dataset.get('ValueDicts', {})
    rows, schema, previous = [], None, None
    for part in dataset.get('PH', []):
        for record in part.get('DM0', []):
            schema = record.get('S', schema)
            if not schema or len(schema) != len(selects):
                raise ValueError('WOAH table schema changed')
            values = iter(record.get('C', []))
            repeated, nulls = record.get('R', 0), record.get('Ø', 0)
            cells = []
            for i, column in enumerate(schema):
                if repeated & (1 << i):
                    if previous is None:
                        raise ValueError('Invalid Power BI repeat mask')
                    cell = previous[i]
                elif nulls & (1 << i):
                    cell = None
                else:
                    try:
                        cell = next(values) if 'C' in record else record[column['N']]
                    except (StopIteration, KeyError) as exc:
                        raise ValueError('Invalid Power BI row') from exc
                    if 'DN' in column and isinstance(cell, int):
                        cell = dictionaries[column['DN']][cell]
                cells.append(cell)
            sentinel = object()
            if next(values, sentinel) is not sentinel:
                raise ValueError('Unexpected Power BI cells')
            previous = cells
            rows.append({selects[i]['Name']: value for i, value in enumerate(cells)})
    if not rows:
        raise ValueError('WOAH source returned an empty table; verify the dashboard')
    return rows


def normalize_row(row):
    def field(suffix):
        matches = [value for key, value in row.items() if key.endswith(suffix)]
        if len(matches) != 1:
            raise ValueError(f'Missing or ambiguous WOAH field: {suffix}')
        return matches[0]
    name = field('.Self-declared freedom from')
    code = disease_code(name or '')
    if not code:
        return None
    country = field('.Country')
    if not isinstance(country, str) or not country.strip():
        raise ValueError('WOAH row has no member name')
    coverage = field('.Coverage')
    published = field('.Date of 1st publication')
    if isinstance(published, (int, float)):
        published = datetime.fromtimestamp(published / 1000, timezone.utc).date().isoformat()
    link = field('.Link_EN)')
    if link is not None and not isinstance(link, str):
        raise ValueError('Invalid PDF URL field')
    # The report can link to a non-English original; preserve this fact for GPT.
    metadata = dict(row, source_page=SOURCE_URL, coverage=coverage,
                    language_note='Link_EN may contain an original-language publication')
    identity = json.dumps([country, name, coverage, published, link], ensure_ascii=False)
    return {'source_identity': identity, 'disease': code, 'country': country,
            'title': f'{country} — {name} ({coverage})', 'published_date': published,
            'status': 'PUBLISHED_SELF_DECLARATION', 'pdf_url': (link or '').strip() or None,
            'metadata': metadata}


def discover_documents(timeout=90):
    from playwright.sync_api import sync_playwright
    captured, errors = [], []
    def receive(response):
        if '/querydata' not in response.url.lower() or response.status != 200:
            return
        try:
            payload = response.json()
            for result in payload.get('results', []):
                table = decode_table(result.get('result', {}).get('data', {}))
                if table is not None:
                    captured.append(table)
        except Exception as exc:
            errors.append(str(exc))
    with sync_playwright() as p:
        channel = os.getenv('WOAH_BROWSER_CHANNEL', 'msedge' if os.name == 'nt' else '')
        browser = p.chromium.launch(headless=True, **({'channel': channel} if channel else {}))
        try:
            page = browser.new_page(locale='en-US')
            page.on('response', receive)
            page.goto(os.getenv('WOAH_REPORT_URL', REPORT_URL),
                      wait_until='domcontentloaded', timeout=timeout * 1000)
            deadline = time.monotonic() + timeout
            while not captured and time.monotonic() < deadline:
                page.wait_for_timeout(500)
            if not captured:
                raise RuntimeError('WOAH document list unavailable: ' + '; '.join(errors[-3:]))
            docs = [normalize_row(row) for row in captured[-1]]
            return [doc for doc in docs if doc is not None]
        finally:
            browser.close()


def validate_pdf_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https' or not (host == 'woah.org' or host.endswith('.woah.org')):
        raise ValueError('Only HTTPS WOAH document URLs are accepted')
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Invalid WOAH document URL')


def download_pdf(url, max_bytes=20 * 1024 * 1024):
    # HTTPAdapter cannot retry a connection dropped after streaming begins.
    for attempt in range(3):
        try:
            return _download_pdf_once(url, max_bytes)
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def _download_pdf_once(url, max_bytes):
    validate_pdf_url(url)
    session = requests.Session()
    retry = Retry(total=3, connect=3, read=3, status=3, backoff_factor=1,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=('GET',))
    session.mount('https://', HTTPAdapter(max_retries=retry))
    session.headers['User-Agent'] = 'WAHIS-WOAH-DocumentCollector/1.0'
    try:
        # Validate every redirect before making another request.
        for _ in range(6):
            with session.get(url, stream=True, timeout=(15, 90), allow_redirects=False) as response:
                if response.is_redirect:
                    from urllib.parse import urljoin
                    url = urljoin(url, response.headers['Location'])
                    validate_pdf_url(url)
                    continue
                response.raise_for_status()
                if int(response.headers.get('Content-Length') or 0) > max_bytes:
                    raise ValueError('PDF exceeds 20 MB download limit')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError('PDF exceeds 20 MB download limit')
                    chunks.append(chunk)
                pdf = b''.join(chunks)
                if not pdf.lstrip().startswith(b'%PDF-'):
                    raise ValueError('WOAH URL did not return a PDF')
                return pdf
        raise ValueError('Too many PDF redirects')
    finally:
        session.close()


def extract_pages(pdf):
    reader = PdfReader(io.BytesIO(pdf))
    if reader.is_encrypted and not reader.decrypt(''):
        raise ValueError('Password-protected PDF')
    if not 0 < len(reader.pages) <= 200:
        raise ValueError('PDF must have 1 to 200 pages')
    pages = []
    for number, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ''
        except Exception:
            text = ''  # preserve the original; GPT can read the PDF page image
        pages.append({'page': number, 'text': text})
    return pages
