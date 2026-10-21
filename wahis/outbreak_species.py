"""Add outbreak species to every report ingestion path without storing JSON."""
import threading
import time
from functools import lru_cache

import requests

from database.outbreak_species_db import (
    ensure_schema, get_pending_for_outbreaks, save_outbreak_species,
)
from database.db import get_connection
from wahis.detail_api import get_outbreak_detail
from wahis.http_retry import retry_after_seconds


_schema_lock = threading.Lock()
_save_lock = threading.Lock()


@lru_cache(maxsize=1)
def _ensure_schema_once():
    ensure_schema()


def load_report_outbreak_species(data, attempts=5, retry_delay=3):
    ids = []
    for outbreak in data.get('outbreaks') or []:
        if not isinstance(outbreak, dict) or outbreak.get('outbreakId') is None:
            raise ValueError('Report contains an outbreak without outbreakId')
        ids.append(outbreak['outbreakId'])
    if not ids:
        return
    with _schema_lock:
        _ensure_schema_once()
    pending = get_pending_for_outbreaks(ids)
    if not pending:
        return
    conn = None
    try:
        with requests.Session() as session:
            for outbreak_id, report_id in pending:
                for attempt in range(1, attempts + 1):
                    try:
                        detail = get_outbreak_detail(report_id, outbreak_id, session=session)
                        with _save_lock:
                            if conn is None:
                                conn = get_connection()
                            else:
                                conn.ping()
                            category = save_outbreak_species(outbreak_id, report_id, detail,
                                                             connection=conn)
                        print(f'Outbreak species saved: outbreak={outbreak_id} category={category}',
                              flush=True)
                        break
                    except Exception as exc:
                        if conn is not None:
                            try:
                                conn.close()
                            except Exception:
                                pass
                            conn = None
                        print(f'Outbreak species: outbreak={outbreak_id} '
                              f'attempt={attempt}/{attempts}: {exc}', flush=True)
                        if attempt == attempts:
                            raise
                        delay = retry_delay * attempt
                        response = getattr(exc, 'response', None)
                        if response is not None and response.status_code in (429, 503):
                            delay = max(delay, retry_after_seconds(response))
                        time.sleep(delay)
                time.sleep(0.2)
    finally:
        if conn is not None:
            conn.close()
