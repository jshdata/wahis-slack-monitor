import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from database.presence_db import load_presence_data
from slack.presence_app import settings_view
from slack.presence_app import register_presence_handlers
from slack.presence_report import build_presence_report, table_model


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.countries = [('Japan', 'Asia'), ('Korea', 'Asia'), ('USA', 'North America'),
                          ('Brazil', 'South America'), ('Unknown', None)]
        self.facts = {('Japan', 2025, 1), ('Japan', 2025, 2), ('USA', 2026, 3)}
        self.today = date(2026, 10, 15)

    def test_yearly_counts_distinct_country_year_not_outbreaks_or_months(self):
        periods, groups, totals = table_model(self.countries, self.facts, 'year', self.today)
        self.assertEqual(periods, [(2025,), (2026,)])
        self.assertEqual(totals, [1, 1])
        self.assertEqual(dict(groups['Asia'])['Japan'], [1, 0])
        self.assertEqual(dict(groups['Asia'])['Korea'], [0, 0])
        self.assertEqual(len(groups['America']), 2)

    def test_monthly_totals_include_empty_months_and_all_countries(self):
        periods, groups, totals = table_model(self.countries, self.facts, 'month', self.today)
        self.assertEqual(len(periods), 22)
        self.assertIn((2025, 12), periods)
        self.assertEqual(periods[-1], (2026, 10))
        self.assertEqual(sum(totals), 3)
        self.assertEqual(dict(groups['Other'])['Unknown'], [0] * 22)

    def test_merged_headers_blank_cells_and_separate_totals(self):
        html = build_presence_report(self.countries, {'BSE': self.facts}, 'both', self.today)
        self.assertIn('rowspan="2"><span class="region-label">아시아', html)
        self.assertIn('colspan="12">2025년', html)
        self.assertIn('colspan="10">2026년', html)
        self.assertIn('총 O 합계: 2', html)
        self.assertIn('총 O 합계: 3', html)
        self.assertEqual(html.count('<td class="yes">O</td>'), 5)
        self.assertIn('<td></td>', html)
        self.assertNotIn('>X<', html)
        self.assertEqual(html.count('날짜별 O 합계'), 2)
        self.assertIn('BSE - 소해면상뇌증', html)

    def test_empty_disease_and_escaped_country(self):
        html = build_presence_report([('<img>', 'Asia')], {'ASF': set()}, 'year', self.today)
        self.assertIn('&lt;img&gt;', html)
        self.assertIn('총 O 합계: 0', html)
        self.assertIn('저장된 발생일이 없습니다', html)

    def test_settings_only_ask_disease_and_unit(self):
        view = settings_view('BSE')
        inputs = [b for b in view['blocks'] if b['type'] == 'input']
        self.assertEqual([b['block_id'] for b in inputs], ['presence_disease', 'presence_mode'])
        self.assertEqual(inputs[0]['element']['initial_option']['value'], 'BSE')

    @patch('slack.presence_app.POOL')
    @patch('slack.presence_app.report_url', return_value='https://example.test/reports/test')
    @patch('slack.presence_app.load_presence_data')
    def test_modal_generates_html_link_without_sending_messages(self, load, url, pool):
        load.return_value = (self.countries, {'BSE': self.facts})
        handlers = {}
        class App:
            def action(self, name):
                return lambda fn: handlers.setdefault(name, fn)
            def view(self, name):
                return lambda fn: handlers.setdefault(name, fn)
        reports = {}
        register_presence_handlers(App(), reports)
        pool.submit.side_effect = lambda fn: fn()
        client, ack = MagicMock(), MagicMock()
        view = {'state': {'values': {
            'presence_disease': {'select': {'selected_option': {'value': 'BSE'}}},
            'presence_mode': {'select': {'selected_option': {'value': 'both'}}}}}}
        handlers['presence_settings'](ack, {'view': {'id': 'V1'}}, view, client)
        ack.assert_called_once()
        self.assertEqual(len(reports), 1)
        result = client.views_update.call_args.kwargs['view']
        self.assertEqual(result['blocks'][1]['elements'][0]['url'], url.return_value)
        client.chat_postMessage.assert_not_called()
        client.files_upload_v2.assert_not_called()

    @patch('database.presence_db.get_connection')
    def test_database_deduplicates_reports_and_splits_hpai(self, get):
        cursor = get.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [self.countries, [
            ('High pathogenicity avian influenza viruses (Inf. with) (poultry)', 'Japan', 2025, 1),
            ('High pathogenicity avian influenza viruses (Inf. with) (poultry)', 'Japan', 2025, 1)]]
        countries, facts = load_presence_data('HPAI')
        self.assertEqual(countries, self.countries)
        self.assertEqual(facts['HPAI'], {('Japan', 2025, 1)})
        self.assertEqual(facts['HPAI_NON_POULTRY'], set())
        sql, params = cursor.execute.call_args.args
        self.assertIn('SELECT DISTINCT', sql)
        self.assertEqual(len(params), 2)
        get.return_value.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
