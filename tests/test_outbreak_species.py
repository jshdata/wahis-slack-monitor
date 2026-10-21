import unittest
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from database import outbreak_species_db as db
import outbreak_species_load as loader


def response(*flags):
    return {'outbreak': {'outbreakId': 42}, 'speciesQuantities': [
        {'totalQuantities': {'speciesId': i, 'speciesName': 'Birds', 'isWild': flag}}
        for i, flag in enumerate(flags)
    ]}


class OutbreakSpeciesTests(unittest.TestCase):
    @patch.object(db, 'get_connection')
    def test_compact_storage_keeps_species_without_any_json(self, connect):
        conn = connect.return_value
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (100,)
        data = response(False)
        data['controlMeasures'] = [{'name': 'Disinfection'}]
        db.save_outbreak_species(42, 100, data)
        sql, values = cur.executemany.call_args.args
        self.assertNotIn('raw_json', sql)
        self.assertEqual(values, [(42, 0, 100, 0, 'Birds', False)])
        self.assertFalse(any('snapshots' in c.args[0] for c in cur.execute.call_args_list))
        conn.commit.assert_called_once()

    @patch.object(db, 'get_connection')
    def test_pending_no_longer_requires_full_snapshot(self, connect):
        cur = connect.return_value.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [(42, 100)]
        self.assertEqual(db.get_pending(limit=10), [(42, 100)])
        sql, params = cur.execute.call_args.args
        self.assertNotIn('snapshot', sql)
        self.assertIn('species_loaded_report_id <>', sql)
        self.assertEqual(params, (0, 10))

    @patch.object(db, 'get_connection')
    def test_reused_connection_commits_without_closing(self, connect):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (100,)
        self.assertEqual(db.save_outbreak_species(42, 100, response(False), connection=conn), 'domestic')
        conn.commit.assert_called_once()
        conn.close.assert_not_called()
        connect.assert_not_called()

    @patch.object(loader, 'save_outbreak_species', return_value='wild')
    @patch.object(loader, 'get_connection')
    def test_resources_reuse_connections_and_isolate_threads(self, connect, save):
        connect.side_effect = lambda: MagicMock()
        resources = loader.WorkerResources()
        barrier = threading.Barrier(3)

        def work(_):
            barrier.wait(timeout=5)
            resources.save(42, 100, response(True))
            resources.save(42, 100, response(True))
            return resources.current()['connection']

        try:
            with ThreadPoolExecutor(max_workers=3) as executor:
                connections = list(executor.map(work, range(3)))
            self.assertEqual(connect.call_count, 3)
            self.assertEqual(len({id(c) for c in connections}), 3)
            for conn in connections:
                conn.ping.assert_called_once_with()
        finally:
            resources.close()
        for conn in connections:
            conn.close.assert_called_once()

    @patch.object(loader, 'save_outbreak_species')
    @patch.object(loader, 'get_connection')
    def test_db_writes_do_not_overlap_while_requests_run_concurrently(self, connect, save):
        connect.side_effect = lambda: MagicMock()
        resources = loader.WorkerResources()
        request_barrier = threading.Barrier(3)
        active = peak = 0
        guard = threading.Lock()

        def store(*args, **kwargs):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with guard:
                active -= 1
            return 'wild'

        def fetch(*args, **kwargs):
            request_barrier.wait(timeout=5)
            return response(True)

        def work(_):
            return loader.load_one(42, 100, resources.current()['session'],
                                   store=resources.save)

        save.side_effect = store
        try:
            with patch.object(loader, 'get_outbreak_detail', side_effect=fetch):
                with ThreadPoolExecutor(max_workers=3) as executor:
                    self.assertEqual(list(executor.map(work, range(3))), ['wild'] * 3)
            self.assertEqual(peak, 1)
            self.assertEqual(save.call_count, 3)
        finally:
            resources.close()

    @patch.object(loader, 'save_outbreak_species')
    @patch.object(loader, 'get_connection')
    def test_failed_connection_is_replaced_on_retry(self, connect, save):
        first, second = MagicMock(), MagicMock()
        connect.side_effect = [first, second]
        save.side_effect = [RuntimeError('disconnected'), 'wild']
        resources = loader.WorkerResources()
        try:
            with self.assertRaises(RuntimeError):
                resources.save(42, 100, response(True))
            self.assertEqual(resources.save(42, 100, response(True)), 'wild')
            first.close.assert_called_once()
            self.assertIs(resources.current()['connection'], second)
        finally:
            resources.close()

    @patch.object(loader.time, 'sleep')
    @patch.object(loader, 'get_outbreak_detail')
    def test_rate_limit_cooldown_shared_even_on_last_attempt(self, fetch, sleep):
        res = MagicMock(status_code=429, headers={'Retry-After': '17'})
        fetch.side_effect = loader.requests.HTTPError(response=res)
        gate = MagicMock()
        self.assertIsNone(loader.load_one(42, 100, MagicMock(), attempts=1, gate=gate))
        gate.cooldown.assert_called_once_with(17)
        sleep.assert_not_called()

    def test_retry_after_http_date(self):
        res = MagicMock(headers={'Retry-After': 'Wed, 21 Oct 2099 00:00:00 GMT'})
        self.assertGreater(loader.retry_after_seconds(res), 0)
        res.headers = {'Retry-After': 'invalid'}
        self.assertEqual(loader.retry_after_seconds(res), 0)

    def test_classification_preserves_unknown_and_mixed(self):
        for flags, expected in [((True,), 'wild'), ((False,), 'domestic'),
                                ((True, False), 'mixed'), ((False, None), 'unknown'),
                                ((), 'unknown'), ((True, False, None), 'mixed')]:
            with self.subTest(flags=flags):
                self.assertEqual(db.parse_species(response(*flags), 42)[1], expected)

    def test_malformed_or_wrong_outbreak_cannot_mark_complete(self):
        for data in [response(True), {'outbreak': {'outbreakId': 43}},
                     {'outbreak': {'outbreakId': 43}, 'speciesQuantities': [{}]}]:
            with self.assertRaises(ValueError):
                db.parse_species(data, 43)
        with self.assertRaises(ValueError):
            db.parse_species(response('false'), 42)

    @patch.object(db, 'get_connection')
    def test_failed_insert_rolls_back_without_completion_marker(self, connect):
        conn = connect.return_value
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (100,)
        cur.executemany.side_effect = RuntimeError('write failed')
        with self.assertRaises(RuntimeError):
            db.save_outbreak_species(42, 100, response(False))
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
        self.assertFalse(any('UPDATE outbreaks SET' in call.args[0]
                             for call in cur.execute.call_args_list))

    @patch.object(db, 'get_connection')
    def test_stale_report_cannot_replace_species(self, connect):
        conn = connect.return_value
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (101,)
        with self.assertRaises(ValueError):
            db.save_outbreak_species(42, 100, response(False))
        self.assertEqual(cur.execute.call_count, 1)
        conn.commit.assert_not_called()

    @patch.object(loader.time, 'sleep')
    @patch.object(loader, 'save_outbreak_species', return_value='wild')
    @patch.object(loader, 'get_outbreak_detail')
    def test_request_failure_retries_then_saves(self, fetch, save, sleep):
        fetch.side_effect = [RuntimeError('network'), response(True)]
        self.assertEqual(loader.load_one(42, 100, MagicMock()), 'wild')
        sleep.assert_called_once_with(3)
        save.assert_called_once_with(42, 100, response(True))

    @patch.object(loader.time, 'sleep')
    @patch.object(loader, 'save_outbreak_species')
    @patch.object(loader, 'get_outbreak_detail', side_effect=RuntimeError('network'))
    def test_exhausted_request_never_marks_complete(self, fetch, save, sleep):
        self.assertIsNone(loader.load_one(42, 100, MagicMock(), attempts=3))
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [3, 6])
        save.assert_not_called()

    @patch.object(loader, 'load_one', return_value='domestic')
    @patch.object(loader, 'get_remaining_count', return_value=10)
    @patch.object(loader, 'get_pending', return_value=[(42, 100), (43, 100)])
    def test_batch_limit_passed_to_pending_query(self, pending, remaining, load):
        self.assertEqual(loader.main(['--limit', '2', '--delay', '0']), 0)
        pending.assert_called_once_with(0, 2)
        self.assertEqual(load.call_count, 2)


if __name__ == '__main__':
    unittest.main()
