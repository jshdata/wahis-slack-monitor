import json
import re
import unittest
from datetime import date
from unittest.mock import MagicMock, Mock, patch

from database.dashboard_db import load_dashboard_data
from slack.dashboard_app import dashboard_selection, register_dashboard_handlers
from slack.dashboard_report import build_dashboard_report


class DashboardTests(unittest.TestCase):
    @patch('database.dashboard_db.get_connection')
    def test_query_deduplicates_events_and_outbreaks(self, connect):
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        name = 'African swine fever virus (Inf. with)'
        cursor.__iter__.side_effect = [iter([(7, 'Japan', name), (7, 'Japan', name)]),
                                      iter([('Japan', 'Asia')]),
                                      iter([(date(2024, 2, 29), 7), (date(2024, 2, 29), 7),
                                            (date(2024, 2, 29), 999)])]
        self.assertEqual(load_dashboard_data(date(2026, 10, 16)),
                         [['2024-02-29', 'Japan', 'Asia', 'ASF', 2]])
        sql, params = cursor.execute.call_args.args
        self.assertIn('FROM outbreaks', sql)
        self.assertNotIn('JOIN', sql)
        self.assertTrue(all('GROUP BY' not in call.args[0] for call in cursor.execute.call_args_list))
        self.assertEqual(params[-1], date(2026, 10, 17))
        connect.return_value.close.assert_called_once()

    def test_data_is_safe_and_keeps_all_counts(self):
        rows = [['2026-01-01', '</script><script>alert(1)</script>', 'Asia', 'ASF', 4]]
        html = build_dashboard_report(rows, date(2026, 10, 16), {'disease': 'ASF'})
        self.assertNotIn(rows[0][1], html)
        payload = re.search(r'const DATA=(.*);\n', html).group(1)
        data = json.loads(payload)
        self.assertEqual(data['rows'], rows)
        self.assertEqual(data['initial']['disease'], 'ASF')
        self.assertIn('/assets/plotly-', html)

    def test_selection_parses_direct_dates_and_rejects_invalid_ranges(self):
        values = {'stats_start_text_block': {'stats_start_text': {'value': '20240101'}},
                  'stats_start_date_block': {'stats_start_date': {'selected_date': '2025-01-01'}},
                  'stats_end_date_block': {'stats_end_date': {'selected_date': '2024-12-31'}}}
        self.assertEqual(dashboard_selection(values)['start'], '2024-01-01')
        values['stats_start_text_block']['stats_start_text']['value'] = '20250230'
        with self.assertRaises(ValueError):
            dashboard_selection(values)
        values['stats_start_text_block']['stats_start_text']['value'] = '20260101'
        with self.assertRaises(ValueError):
            dashboard_selection(values)

    @patch('slack.dashboard_app.POOL')
    @patch('slack.dashboard_app.load_dashboard_data', return_value=[])
    @patch('slack.dashboard_app.report_url', return_value='https://example.test/reports/token')
    def test_slack_button_generates_report_without_posting_messages(self, url, load, pool):
        handlers = {}
        class App:
            def action(self, name):
                def register(function):
                    handlers[name] = function
                    return function
                return register
        pool.submit.side_effect = lambda work: work()
        reports = {}
        register_dashboard_handlers(App(), reports)
        client = MagicMock()
        client.views_push.return_value = {'view': {'id': 'V1'}}
        ack = Mock()
        handlers['dashboard_open'](ack, {'trigger_id': 'T1', 'view': {'state': {'values': {}}}}, client)
        ack.assert_called_once()
        self.assertEqual(len(reports), 1)
        self.assertIn('동물질병 통계 대시보드', next(iter(reports.values()))['html'])
        client.views_update.assert_called_once()
        client.chat_postMessage.assert_not_called()


if __name__ == '__main__':
    unittest.main()
