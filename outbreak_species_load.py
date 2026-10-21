"""Load only outbreak animal categories and species; do not store API JSON."""
import argparse
import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from database.outbreak_species_db import (
    ensure_schema, get_pending, get_remaining_count, save_outbreak_species,
)
from wahis.detail_api import get_outbreak_detail
from database.db import get_connection
from wahis.http_retry import retry_after_seconds


class RequestGate:
    """Share request spacing and server cooldown across all workers."""
    def __init__(self, delay):
        self.delay = delay
        self.next_request = 0
        self.lock = threading.Lock()

    def wait(self):
        while True:
            with self.lock:
                remaining = self.next_request - time.monotonic()
                if remaining <= 0:
                    self.next_request = time.monotonic() + self.delay
                    return
            time.sleep(min(remaining, 0.5))

    def cooldown(self, seconds):
        with self.lock:
            self.next_request = max(self.next_request, time.monotonic() + seconds)


class WorkerResources:
    """Each thread owns its own HTTP session and MySQL connection."""
    def __init__(self):
        self.local = threading.local()
        self.resources = []
        self.lock = threading.Lock()
        self.save_lock = threading.Lock()

    def current(self):
        if not hasattr(self.local, 'resource'):
            resource = {'session': requests.Session(), 'connection': None}
            self.local.resource = resource
            with self.lock:
                self.resources.append(resource)
        return self.local.resource

    def save(self, outbreak_id, report_id, data):
        # Hold through commit/rollback and connection disposal. HTTP requests and
        # retry sleeps remain outside this lock so other workers can progress.
        with self.save_lock:
            return self._save(outbreak_id, report_id, data)

    def _save(self, outbreak_id, report_id, data):
        resource = self.current()
        try:
            if resource['connection'] is None:
                resource['connection'] = get_connection()
            else:
                resource['connection'].ping()
            return save_outbreak_species(outbreak_id, report_id, data,
                                         connection=resource['connection'])
        except Exception:
            conn, resource['connection'] = resource['connection'], None
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            raise

    def close(self):
        for resource in self.resources:
            resource['session'].close()
            if resource['connection'] is not None:
                resource['connection'].close()


def load_one(outbreak_id, report_id, session, attempts=5, retry_delay=3,
             store=None, gate=None):
    for attempt in range(1, attempts + 1):
        try:
            if gate is not None:
                gate.wait()
            data = get_outbreak_detail(report_id, outbreak_id, session=session)
            category = (store or save_outbreak_species)(outbreak_id, report_id, data)
            return category
        except Exception as exc:
            print(f'outbreak={outbreak_id} attempt={attempt}/{attempts}: {exc}', flush=True)
            wait_seconds = retry_delay * attempt
            response = getattr(exc, 'response', None)
            if response is not None and response.status_code in (429, 503):
                wait_seconds = max(wait_seconds, retry_after_seconds(response))
                if gate is not None:
                    gate.cooldown(wait_seconds)
            if attempt == attempts:
                return None
            time.sleep(wait_seconds)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group()
    group.add_argument('--limit', type=int, default=100, help='Maximum outbreaks attempted (default: 100)')
    group.add_argument('--all', action='store_true', help='Process all pending outbreaks')
    p.add_argument('--max-minutes', type=float, help='Stop before starting another outbreak after this time')
    p.add_argument('--delay', type=float, default=0.2, help='Minimum seconds between all API request starts (default: 0.2)')
    p.add_argument('--workers', type=int, default=3, help='Concurrent workers, each with its own DB connection (default: 3)')
    p.add_argument('--attempts', type=int, default=5, help='Total attempts per outbreak')
    p.add_argument('--retry-delay', type=float, default=3, help='Linear retry delay in seconds (default: 3)')
    p.add_argument('--init-schema', action='store_true', help='Create storage columns/table if missing')
    p.add_argument('--status', action='store_true', help='Show pending count without API requests')
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.limit <= 0 or args.attempts <= 0 or args.workers <= 0:
        p.error('--limit, --attempts and --workers must be positive')
    for name in ('delay', 'retry_delay', 'max_minutes'):
        value = getattr(args, name)
        if value is not None and (not math.isfinite(value) or value < 0 or
                                  (name == 'max_minutes' and value == 0)):
            p.error(f'Invalid --{name.replace("_", "-")}')
    print('Starting outbreak category + species loader (no JSON storage)...', flush=True)
    if args.init_schema:
        print('Initializing DB schema (connection / ALTER TABLE may take time)...', flush=True)
        ensure_schema()
        print('DB schema ready.', flush=True)
    print('Counting pending outbreaks...', flush=True)
    remaining = get_remaining_count()
    print(f'Pending outbreaks: {remaining}', flush=True)
    if args.status:
        return 0
    start = time.monotonic()
    attempted = succeeded = after_id = 0
    failed = []
    limit = remaining if args.all else min(args.limit, remaining)
    interrupted = False
    resources = WorkerResources()
    gate = RequestGate(args.delay)

    def work(outbreak_id, report_id):
        return load_one(outbreak_id, report_id, resources.current()['session'],
                        args.attempts, args.retry_delay, store=resources.save, gate=gate)

    def record(future, outbreak_id):
        nonlocal succeeded, completed
        category = future.result()
        completed += 1
        if category is None:
            failed.append(outbreak_id)
        else:
            succeeded += 1
        elapsed = time.monotonic() - start
        print(f'[{completed}/{limit}] outbreak={outbreak_id} '
              f'category={category or "FAILED"} elapsed={elapsed:.1f}s '
              f'average={elapsed / completed:.2f}s/outbreak', flush=True)

    completed = 0
    print(f'Workers={args.workers} DB writes=1 global request interval={args.delay}s', flush=True)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            while attempted < limit:
                if args.max_minutes and time.monotonic() - start >= args.max_minutes * 60:
                    break
                batch = get_pending(after_id, min(100, limit - attempted))
                if not batch:
                    break
                for offset in range(0, len(batch), args.workers):
                    if args.max_minutes and time.monotonic() - start >= args.max_minutes * 60:
                        break
                    futures = {}
                    recorded = set()
                    try:
                        for outbreak_id, report_id in batch[offset:offset + args.workers]:
                            future = executor.submit(work, outbreak_id, report_id)
                            futures[future] = outbreak_id
                            after_id = outbreak_id
                            attempted += 1
                        for future in as_completed(futures):
                            record(future, futures[future])
                            recorded.add(future)
                    except KeyboardInterrupt:
                        print('Stopping new requests; waiting for active outbreaks to finish...', flush=True)
                        for future in as_completed(futures):
                            if future not in recorded:
                                record(future, futures[future])
                        raise
    except KeyboardInterrupt:
        interrupted = True
        print('Stopped. Committed outbreaks will be skipped on the next run.', flush=True)
    finally:
        resources.close()
    elapsed = time.monotonic() - start
    print(f'Attempted={attempted} success={succeeded} failed={len(failed)} '
          f'elapsed={elapsed:.1f}s pending={get_remaining_count()}', flush=True)
    if failed:
        print(f'Failed outbreak IDs (remain pending): {failed}', flush=True)
    return 130 if interrupted else (1 if failed else 0)


if __name__ == '__main__':
    raise SystemExit(main())
