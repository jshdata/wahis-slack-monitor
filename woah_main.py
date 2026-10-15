"""Collect WOAH PDFs into MySQL and export originals for manual ChatGPT use."""
import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone

from database import woah_db
from woah.collector import DISEASES, discover_documents, download_pdf, extract_pages

logger = logging.getLogger(__name__)


def sync(diseases, retry_failed=False):
    woah_db.ensure_schema()
    try:
        documents = discover_documents()
    except Exception as exc:
        for disease in diseases:
            woah_db.record_run(disease, 'COLLECTION_FAILED', error=str(exc)[:2000])
        raise
    results = {}
    for disease in diseases:
        selected = [doc for doc in documents if doc['disease'] == disease]
        saved = failed = skipped = 0
        existing = {doc['source_key']: doc for doc in woah_db.list_documents(disease)} if retry_failed else {}
        for doc in selected:
            key = hashlib.sha256(doc['source_identity'].encode('utf-8')).hexdigest()
            if key in existing and existing[key]['download_status'] == 'READY':
                skipped += 1
                continue
            document_id = woah_db.upsert_document(doc)
            if not doc['pdf_url']:
                woah_db.download_failed(document_id, 'No document link in the source table', 'NO_PDF_LINK')
                continue
            try:
                pdf = download_pdf(doc['pdf_url'])
                pages = extract_pages(pdf)
                woah_db.save_pdf(document_id, pdf, pages)
                saved += 1
                logger.info('Saved %s document %s: %s bytes / %s pages',
                            disease, document_id, len(pdf), len(pages))
            except Exception as exc:
                failed += 1
                woah_db.download_failed(document_id, exc)
                logger.warning('PDF download failed: document %s (%s)', document_id, type(exc).__name__)
                continue
        status = 'NO_DOCUMENTS' if not selected else ('PARTIAL' if failed else 'SUCCESS')
        woah_db.record_run(disease, status, len(selected), saved + skipped, failed)
        results[disease] = dict(status=status, found=len(selected), saved=saved,
                                skipped=skipped, failed=failed)
    return results


def retry_scheduled(diseases, now=None):
    """At 10:00 KST retry partial runs, or fully recover missed daily runs."""
    now = now or datetime.now(timezone.utc)
    cutoff = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    woah_db.ensure_schema()
    full, partial = [], []
    for disease in diseases:
        run = woah_db.latest_run(disease)
        checked = run['checked_at'].replace(tzinfo=timezone.utc) if run else None
        if not run or checked < cutoff or run['status'] == 'COLLECTION_FAILED':
            full.append(disease)
        elif run['status'] == 'PARTIAL':
            partial.append(disease)
    results = {}
    if full:
        results.update(sync(full))
    if partial:
        results.update(sync(partial, retry_failed=True))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disease', nargs='+', choices=list(DISEASES), default=list(DISEASES))
    parser.add_argument('--schema-only', action='store_true')
    parser.add_argument('--discover-only', action='store_true', help='Read public list without connecting to MySQL')
    parser.add_argument('--retry-failed', action='store_true', help='Retry missing/failed PDFs without downloading ready documents')
    parser.add_argument('--retry-scheduled', action='store_true', help='Retry failed or missed daily collections; skip successful runs today')
    parser.add_argument('--export-id', type=int, help='Export stored PDF and ChatGPT prompt for one document')
    parser.add_argument('--output-dir', default='woah_exports', help='Local PDF export directory')
    args = parser.parse_args()
    if args.discover_only:
        docs = discover_documents()
        print(json.dumps([doc for doc in docs if doc['disease'] in args.disease], ensure_ascii=False, indent=2))
    elif args.schema_only:
        woah_db.ensure_schema()
        print('WOAH schema ready')
    elif args.export_id:
        from woah.chatgpt import export_document
        for path in export_document(args.export_id, args.output_dir):
            print(path)
    else:
        results = (retry_scheduled(args.disease) if args.retry_scheduled
                   else sync(args.disease, retry_failed=args.retry_failed))
        print(json.dumps(results, ensure_ascii=False, indent=2))
        if any(result['failed'] for result in results.values()):
            raise SystemExit(1)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
