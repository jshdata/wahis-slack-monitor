"""Load one disease's historical events and details without Slack alerts."""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import local

import requests

from database.db import get_connection, insert_disease_report
from database.detail_db import save_report_detail
from wahis.api import DISEASES, get_events
from wahis.detail_api import get_report_detail

WORKER = local()


def load_report_detail(report_id):
    if not hasattr(WORKER, 'session'):
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        WORKER.session = requests.Session()
        WORKER.session.mount('https://', HTTPAdapter(max_retries=Retry(
            total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))))
    for attempt in range(3):
        try:
            save_report_detail(get_report_detail(report_id, session=WORKER.session))
            return True
        except Exception as error:
            print(f'{report_id}: retry {attempt + 1}/3 ({type(error).__name__})', flush=True)
            time.sleep(attempt + 1)
    return False


def fetch_page(code, page, page_size):
    for attempt in range(4):
        try:
            return get_events(page_number=page, page_size=page_size, disease_codes=[code])
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(attempt + 1)


def detail_is_loaded(report_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT detail_loaded FROM disease_reports WHERE report_id=%s', (report_id,))
            row = cursor.fetchone()
            return bool(row and row[0])
    finally:
        conn.close()


def backfill(code, page_size=100):
    page, seen, failed, history = 0, set(), [], []
    while True:
        data = fetch_page(code, page, page_size)
        events = data.get('list')
        total = data.get('totalSize')
        if not isinstance(events, list) or not isinstance(total, int):
            raise ValueError('Unexpected WAHIS list response')
        if not events and len(seen) < total:
            raise ValueError('WAHIS returned an incomplete history')
        new_ids = {event['reportId'] for event in events} - seen
        if events and not new_ids:
            raise ValueError('WAHIS repeated a page; refusing incomplete history')
        for event in events:
            report_id = event['reportId']
            if report_id in seen:
                continue
            seen.add(report_id)
            history.append(event)
        if len(seen) >= total:
            break
        page += 1
    # Process each event in order internally; reports for independent events
    # may load concurrently without racing updates to the same outbreak.
    groups = {}
    for event in history:
        groups.setdefault(event.get('eventId', event['reportId']), []).append(event)

    def load_event(events):
        failures = []
        for event in events:
            report_id = event['reportId']
            # Historical suppression is atomic with the INSERT. Existing rows
            # retain their Slack delivery state.
            insert_disease_report(event, notify_slack=False)
            if not detail_is_loaded(report_id) and not load_report_detail(report_id):
                failures.append(report_id)
            time.sleep(0.5)
        return failures

    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(load_event, events): events for events in groups.values()}
        done = 0
        for job in as_completed(jobs):
            failed.extend(job.result())
            done += len(jobs[job])
            print(f'{code} {done}/{len(history)} reports processed', flush=True)
    print(f'{code}: reports={len(seen)}, detail_failures={failed}', flush=True)
    return not failed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disease', required=True, choices=list(DISEASES))
    args = parser.parse_args()
    raise SystemExit(0 if backfill(args.disease) else 1)
