import json
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from database.neighbors_db import NEIGHBORS, get_neighbor_stats
from slack.neighbors_app import build_neighbor_report, result_blocks, settings_view, register_neighbor_handlers


class NeighborTests(unittest.TestCase):
    @patch('database.neighbors_db.get_connection')
    def test_fixed_18_rows_zero_fill_and_china_merged_in_sql(self, get):
        cursor = get.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [('African swine fever virus (Inf. with)', 14, 5, date(2026, 10, 1))]
        result = get_neighbor_stats('ASF', '2026-01-01', '2026-10-15')
        rows = result['diseases']['ASF']
        self.assertEqual(len(NEIGHBORS), 18)
        self.assertEqual(len(rows), 18)
        self.assertEqual(rows[14], {'country': '중국(본토·홍콩)', 'count': 5, 'latest': '2026-10-01'})
        self.assertEqual(rows[0]['count'], 0)
        sql, params = cursor.execute.call_args.args
        self.assertIn('COUNT(DISTINCT o.outbreak_id)', sql)
        self.assertIn('DATE(MAX(o.start_date))', sql)
        self.assertIn('THEN 14', sql)
        self.assertIn("China (People's Rep. of)", params)
        self.assertIn('Hong Kong', params)
        self.assertEqual(params[-2:], ['2026-01-01', '2026-10-15'])

    @patch('database.neighbors_db.get_connection')
    def test_hpai_has_two_tables_and_defaults_to_first_outbreak(self, get):
        cursor = get.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (date(2005, 1, 1),)
        cursor.fetchall.return_value = []
        result = get_neighbor_stats('HPAI', end_date='2026-10-15')
        self.assertEqual(result['start'], '2005-01-01')
        self.assertEqual(set(result['diseases']), {'HPAI', 'HPAI_NON_POULTRY'})
        for rows in result['diseases'].values():
            self.assertEqual(len(rows), 18)
            self.assertTrue(all(row['count'] == 0 and row['latest'] is None for row in rows))
        html = build_neighbor_report(result)
        self.assertEqual(html.count('<table>'), 2)
        self.assertIn('최근 발생일', html)
        self.assertIn('중국(본토·홍콩)', html)
        blocks = result_blocks(result)
        self.assertTrue(all(len(b['text']['text']) < 3000 for b in blocks))

    def test_settings_have_no_country_filter(self):
        view = settings_view('ASF')
        self.assertEqual([b['block_id'] for b in view['blocks'] if b['type'] == 'input'],
                         ['neighbors_disease', 'neighbors_start', 'neighbors_end'])

    @patch('slack.neighbors_app.POOL')
    @patch('slack.neighbors_app.get_neighbor_stats')
    def test_handler_acknowledges_before_query_without_messages(self, query, pool):
        query.return_value = {'start': '2026-01-01', 'end': '2026-10-15', 'diseases': {
            'ASF': [{'country': name, 'count': 0, 'latest': None} for name, _ in NEIGHBORS]}}
        handlers = {}
        class App:
            def action(self, name):
                return lambda fn: handlers.setdefault(name, fn)
            def view(self, name):
                return lambda fn: handlers.setdefault(name, fn)
        reports = {}
        register_neighbor_handlers(App(), reports)
        pool.submit.side_effect = lambda fn: fn()
        ack, client = MagicMock(), MagicMock()
        query.side_effect = lambda *args: (ack.assert_called_once() or query.return_value)
        view = {'state': {'values': {
            'neighbors_disease': {'select': {'selected_option': {'value': 'ASF'}}},
            'neighbors_start': {'date': {'selected_date': '2026-01-01'}},
            'neighbors_end': {'date': {'selected_date': '2026-10-15'}}}}}
        handlers['neighbors_settings'](ack, {'view': {'id': 'V1'}}, view, client)
        self.assertEqual(len(reports), 1)
        self.assertIn('주변국 ASF', json.dumps(client.views_update.call_args.kwargs['view'], ensure_ascii=False))
        client.chat_postMessage.assert_not_called()


if __name__ == '__main__':
    unittest.main()
