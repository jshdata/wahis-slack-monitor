import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import backfill_disease
from database import db, query_db, stats_db
from wahis import api


class BseTests(unittest.TestCase):
    def test_bse_is_available_in_both_slack_menus(self):
        source = ast.parse(Path('slack/query_app.py').read_text(encoding='utf-8'))
        options = {}
        for node in source.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ('DISEASE_OPTIONS', 'STATS_DISEASE_OPTIONS'):
                        options[target.id] = ast.literal_eval(node.value)
        self.assertEqual(len(options), 2)
        for menu in options.values():
            self.assertIn('BSE', [option['value'] for option in menu])

    @patch('wahis.api.requests.post')
    def test_bse_filter_and_regular_monitoring(self, post):
        post.return_value.json.return_value = {'list': []}
        api.get_events(disease_codes=['BSE'])
        self.assertEqual(post.call_args.kwargs['json']['firstDiseases'], [89])
        api.get_events()
        self.assertIn(89, post.call_args.kwargs['json']['firstDiseases'])
        self.assertEqual(query_db.DISEASE_MAP['BSE'], [stats_db.DISEASE_MAP['BSE']])

    @patch('database.db.get_connection')
    def test_history_insert_suppresses_alerts_atomically(self, get):
        event = dict(reportId=1, eventId=2, country='UK', disease='Bovine spongiform encephalopathy ',
                     submissionDate='2026-10-09T08:58:59.651+00:00')
        cursor = get.return_value.cursor.return_value
        db.insert_disease_report(event, notify_slack=False)
        sql, params = cursor.execute.call_args.args
        self.assertEqual(params[-1], 1)
        self.assertNotIn('slack_sent', sql.split('ON DUPLICATE KEY UPDATE')[1])
        db.insert_disease_report(event)
        self.assertEqual(cursor.execute.call_args.args[1][-1], 0)

    @patch('backfill_disease.time.sleep')
    @patch('backfill_disease.load_report_detail', return_value=True)
    @patch('backfill_disease.detail_is_loaded', return_value=False)
    @patch('backfill_disease.insert_disease_report')
    @patch('backfill_disease.fetch_page')
    def test_backfill_saves_details_without_notifications(self, fetch, insert, loaded, detail, sleep):
        fetch.return_value = {'list': [{'reportId': 1}], 'totalSize': 1}
        self.assertTrue(backfill_disease.backfill('BSE'))
        insert.assert_called_once_with({'reportId': 1}, notify_slack=False)
        detail.assert_called_once_with(1)

    @patch('backfill_disease.fetch_page', return_value={'list': [], 'totalSize': 5})
    def test_incomplete_history_is_an_error(self, fetch):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            backfill_disease.backfill('BSE')


if __name__ == '__main__':
    unittest.main()
