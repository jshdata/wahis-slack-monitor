import csv
import gzip
import hashlib
import io
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from slack_sdk.models.views import View
from wahis import control_storage as storage
from slack import control_measures_app as ui


def sample():
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(storage.HEADERS)
    writer.writerows([
        (2026, 'Jan-Jun 2026', 'Asia', 'Japan', 'poultry', 'Domestic', 'Birds', 'Official vaccination'),
        (2026, 'Jul-Dec 2026', 'Asia', 'Japan', 'non-poultry', 'Wild', 'Birds', 'Vaccination prohibited'),
        (2025, 'Jan-Jun 2025', 'Asia', 'Korea', 'poultry', 'Domestic', 'Birds', 'Movement control'),
        (2026, 'Jan-Jun 2026', 'Asia', '100% Test', 'poultry', 'Domestic', 'Birds', 'Movement control'),
    ])
    return stream.getvalue()


class ControlStorageTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        storage.populate(self.conn, [{'rows': 4}], lambda _: io.StringIO(sample()))

    def tearDown(self):
        self.conn.close()

    def test_filters_preserve_hpai_scope_and_do_not_count_animals(self):
        result = storage.query_rows(self.conn, {'country': 'Japan', 'scope': 'vaccination'})
        self.assertEqual(result['total'], 2)
        self.assertEqual({r['disease'] for r in result['rows']}, {'poultry', 'non-poultry'})
        self.assertEqual(storage.query_rows(self.conn, {'year': '2026', 'semester': '1', 'scope': 'official'})['total'], 1)
        self.assertEqual(storage.query_rows(self.conn, {'year': '2025'})['total'], 1)

    def test_country_search_escapes_wildcards_and_sql(self):
        self.assertEqual(storage.query_rows(self.conn, {'country': '%'})['total'], 1)
        self.assertEqual(storage.query_rows(self.conn, {'country': "Japan' OR 1=1 --"})['total'], 0)

    def test_row_mismatch_is_rejected(self):
        conn = sqlite3.connect(':memory:')
        try:
            with self.assertRaisesRegex(ValueError, 'row count'):
                storage.populate(conn, [{'rows': 3}], lambda _: io.StringIO(sample()))
        finally:
            conn.close()

    def test_pagination_clamps_and_returns_all_columns(self):
        result = storage.query_rows(self.conn, {}, page=999)
        self.assertEqual(result['page'], 0)
        self.assertEqual(len(result['rows']), 4)
        self.assertEqual(len(result['rows'][0]), 8)

    def test_download_corruption_never_publishes_local_cache(self):
        digest = hashlib.sha256(b'expected').hexdigest()
        body = MagicMock()
        body.iter_chunks.return_value = [b'corrupt!']
        client = MagicMock()
        client.get_object.return_value = {'Body': body}
        entry = {'code': 'ASF', 'sha256': digest, 'bytes': 8, 'key': 'test', 'rows': 4}
        with tempfile.TemporaryDirectory() as tmp, patch('wahis.control_storage.tempfile.gettempdir', return_value=tmp), \
             patch('wahis.control_storage.pdf_storage.client', return_value=client), \
             patch('wahis.control_storage.pdf_storage.bucket', return_value='test'):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                storage.local_snapshot('ASF', {'files': [entry]})
            from pathlib import Path
            self.assertEqual(list(Path(tmp).rglob('*.sqlite')), [])

    def test_download_validates_and_reuses_sqlite_cache(self):
        raw = gzip.compress(sample().encode())
        digest = hashlib.sha256(raw).hexdigest()
        body = MagicMock()
        body.iter_chunks.return_value = [raw]
        client = MagicMock()
        client.get_object.return_value = {'Body': body}
        entry = {'code': 'HPAI', 'sha256': digest, 'bytes': len(raw), 'key': 'test', 'rows': 4}
        with tempfile.TemporaryDirectory() as tmp, patch('wahis.control_storage.tempfile.gettempdir', return_value=tmp), \
             patch('wahis.control_storage.pdf_storage.client', return_value=client), \
             patch('wahis.control_storage.pdf_storage.bucket', return_value='test'):
            first = storage.local_snapshot('HPAI', {'files': [entry]})
            self.assertEqual(storage.local_snapshot('HPAI', {'files': [entry]}), first)
            client.get_object.assert_called_once()

    def test_slack_settings_and_results_validate_without_network(self):
        settings = ui.settings()
        View(**settings).validate_json()
        self.assertTrue(all(b['type'] == 'input' for b in settings['blocks'][1:]))
        result = storage.query_rows(self.conn, {}, snapshot_at='2026-10-19')
        with patch.object(storage, 'query', return_value=result):
            view = ui.result_view({'disease': 'HPAI', 'country': '', 'year': 'all'})
        View(**view).validate_json()
        self.assertIn('접종 마릿수', str(view))

