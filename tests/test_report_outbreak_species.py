import unittest
from unittest.mock import patch

from database import detail_db, outbreak_species_db
from wahis import outbreak_species as service
from wahis.diseases import DISEASE_NAMES


class ReportSpeciesTests(unittest.TestCase):
    @patch.object(outbreak_species_db, 'get_connection')
    def test_pending_selection_deduplicates_ids_and_uses_current_version(self, connect):
        cur = connect.return_value.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [(42, 101)]
        self.assertEqual(outbreak_species_db.get_pending_for_outbreaks([42, 42]), [(42, 101)])
        sql, params = cur.execute.call_args.args
        self.assertIn('COALESCE(last_update_report_id, created_by_report_id)', sql)
        self.assertIn('species_loaded_report_id <>', sql)
        self.assertEqual(params, (42,))

    @patch.object(detail_db, 'get_connection')
    def test_reingestion_resets_completion_for_recovery(self, connect):
        detail_db.update_disease_report_detail({'report': {'reportId': 100}})
        sql = connect.return_value.cursor.return_value.execute.call_args.args[0]
        self.assertIn('detail_loaded = 0', sql)

    def test_report_completes_only_after_species_save(self):
        calls = []
        data = {'report': {'reportId': 100}, 'event': {'disease': DISEASE_NAMES['ASF']}}
        with patch.object(detail_db, 'update_disease_report_detail'), \
                patch.object(detail_db, 'insert_outbreaks'), \
                patch.object(detail_db, 'insert_quantitative_data'), \
                patch.object(detail_db, 'load_report_outbreak_species',
                             side_effect=lambda data: calls.append('species')), \
                patch.object(detail_db, 'mark_detail_loaded',
                             side_effect=lambda report: calls.append('complete')):
            detail_db.save_report_detail(data)
        self.assertEqual(calls, ['species', 'complete'])

    def test_species_failure_leaves_report_incomplete(self):
        data = {'report': {'reportId': 100}, 'event': {'disease': DISEASE_NAMES['ASF']}}
        with patch.object(detail_db, 'update_disease_report_detail'), \
                patch.object(detail_db, 'insert_outbreaks'), \
                patch.object(detail_db, 'insert_quantitative_data'), \
                patch.object(detail_db, 'load_report_outbreak_species', side_effect=RuntimeError('failed')), \
                patch.object(detail_db, 'mark_detail_loaded') as mark:
            with self.assertRaises(RuntimeError):
                detail_db.save_report_detail(data)
            mark.assert_not_called()

    @patch.object(service, '_ensure_schema_once')
    @patch.object(service, 'get_pending_for_outbreaks', return_value=[])
    @patch.object(service, 'get_outbreak_detail')
    def test_completed_species_skip_api(self, fetch, pending, schema):
        service.load_report_outbreak_species({'outbreaks': [{'outbreakId': 42}]})
        pending.assert_called_once_with([42])
        fetch.assert_not_called()

    @patch.object(service.time, 'sleep')
    @patch.object(service, '_ensure_schema_once')
    @patch.object(service, 'get_pending_for_outbreaks', return_value=[(42, 101), (43, 101)])
    @patch.object(service, 'get_connection')
    @patch.object(service, 'save_outbreak_species', return_value='wild')
    @patch.object(service, 'get_outbreak_detail')
    def test_retries_current_version_and_reuses_db(self, fetch, save, connect, pending, schema, sleep):
        fetch.side_effect = [RuntimeError('network'), {'value': 42}, {'value': 43}]
        service.load_report_outbreak_species({'outbreaks': [{'outbreakId': 42}, {'outbreakId': 43}]})
        self.assertEqual(fetch.call_args_list[0].args, (101, 42))
        self.assertEqual(fetch.call_args_list[1].args, (101, 42))
        connect.assert_called_once()
        self.assertEqual(save.call_count, 2)
        connect.return_value.ping.assert_called_once_with()
        self.assertIn(3, [call.args[0] for call in sleep.call_args_list])

    @patch.object(service.time, 'sleep')
    @patch.object(service, '_ensure_schema_once')
    @patch.object(service, 'get_pending_for_outbreaks', return_value=[(42, 100)])
    @patch.object(service, 'get_outbreak_detail', side_effect=RuntimeError('network'))
    def test_exhausted_attempts_propagate_to_report_recovery(self, fetch, pending, schema, sleep):
        with self.assertRaises(RuntimeError):
            service.load_report_outbreak_species({'outbreaks': [{'outbreakId': 42}]}, attempts=2)
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(3)


if __name__ == '__main__':
    unittest.main()
