import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

from database.population_db import load_population
from slack.population_app import (FIELDS, option_token, read_filters,
                                  register_population_handlers, settings_view)
from slack.population_report import build_population_report, population_matrix


def record(**changes):
    row = dict(region='Asia', country='Korea (Rep. of)', country_iso3='KOR', year=2024,
               animal_type='Terrestrial', animal_category='Swine', animal_subcategory=None,
               measuring_unit='Animals', live_animals=Decimal('10846000'),
               animal_premises=Decimal('5513'), total_meat_weight_tonnes=Decimal('1132510'))
    return dict(row, **changes)


class PopulationReportTests(unittest.TestCase):
    def test_details_are_separate_from_total_and_missing_is_not_zero(self):
        data = {'years': [2025, 2023, 2024], 'rows': [record(), record(year=2023, live_animals=0),
            record(animal_subcategory='Piglets', live_animals=Decimal('2'),
                   animal_premises=None, total_meat_weight_tonnes=None)]}
        years, rows = population_matrix(data)
        self.assertEqual(years, [2023, 2024, 2025])
        self.assertEqual(len(rows), 4)
        total = next(values for key, metric, values in rows if not key[4] and metric == 'live_animals')
        self.assertEqual(total, [0, Decimal('10846000'), None])
        html = build_population_report(data, date(2026, 10, 16))
        self.assertIn('>2023</th>', html)
        self.assertIn('>10,846,000</td>', html)
        self.assertIn('>0</td>', html)
        self.assertIn('>—</td>', html)
        self.assertIn('<small>Piglets</small>', html)

    def test_units_decimals_and_html_escaping(self):
        html = build_population_report({'years': [2024], 'rows': [record(
            country='<script>bad</script>', measuring_unit='Hives / Nests',
            live_animals=Decimal('12'), total_meat_weight_tonnes=Decimal('1.25'))]}, date.today())
        self.assertNotIn('<script>bad', html)
        self.assertIn('&lt;script&gt;bad', html)
        self.assertIn('벌통·둥지 수 (개)', html)
        self.assertIn('>1.25</td>', html)

    def test_duplicate_reports_fail_instead_of_summing(self):
        with self.assertRaisesRegex(ValueError, '보고서가 여러'):
            population_matrix({'years': [2024], 'rows': [record(), record()]})

    def test_empty_selection_preserves_years(self):
        html = build_population_report({'years': [2023, 2024, 2025], 'rows': []}, date.today())
        self.assertIn('>2025</th>', html)
        self.assertIn('선택 조건에 해당하는 보고 수치가 없습니다.', html)


class PopulationDatabaseTests(unittest.TestCase):
    @patch('database.population_db.population_regions', return_value={'KOR': ['Asia'], 'IRN': ['Asia', 'Middle East']})
    @patch('database.population_db.get_connection')
    def test_parameterized_filters_and_overlapping_regions(self, connect, mapping):
        cur = connect.return_value.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[{'year': 2023}, {'year': 2024}],
                                   [record(), record(country_iso3='IRN', country='Iran')]]
        result = load_population(['Middle East'], ["' OR 1=1 --"], ['Terrestrial'], ['Swine'])
        sql, params = cur.execute.call_args.args
        self.assertNotIn("' OR 1=1", sql)
        self.assertEqual(params, ["' OR 1=1 --", 'Terrestrial', 'Swine'])
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['rows'][0]['region'], 'Asia / Middle East')
        self.assertEqual(result['years'], [2023, 2024])
        connect.return_value.close.assert_called_once()


class PopulationSlackTests(unittest.TestCase):
    def test_filters_and_invalid_selection(self):
        inputs = [b for b in settings_view()['blocks'] if b['type'] == 'input']
        self.assertEqual(len(inputs), 4)
        self.assertTrue(all(b['element']['type'] == 'multi_external_select' for b in inputs))
        self.assertEqual(read_filters({}, {k: [] for k in FIELDS}), {k: [] for k in FIELDS})
        with self.assertRaises(ValueError):
            read_filters({'population_region': {'select': {'selected_options': [{'value': 'invalid'}]}}},
                         {k: [] for k in FIELDS})

    @patch('slack.population_app.POOL')
    @patch('slack.population_app.current_options', return_value={k: [] for k in FIELDS})
    @patch('slack.population_app.load_population', return_value={'years': [2023, 2024, 2025], 'rows': []})
    @patch('slack.population_app.report_url', return_value='https://example.test/reports/token')
    def test_generates_link_without_posting_messages(self, url, load, options, pool):
        handlers = {}
        class App:
            def register(self, name):
                def decorator(function):
                    handlers[name] = function
                    return function
                return decorator
            action = options = view = register
        reports = {}
        pool.submit.side_effect = lambda work: work()
        register_population_handlers(App(), reports)
        client, ack = MagicMock(), Mock()
        handlers['population_settings'](ack, {}, {'id': 'V1', 'state': {'values': {}}}, client)
        load.assert_called_once_with([], [], [], [])
        self.assertIn('>2025</th>', next(iter(reports.values()))['html'])
        result = client.views_update.call_args.kwargs['view']
        self.assertEqual(result['blocks'][1]['elements'][0]['url'], url.return_value)
        client.chat_postMessage.assert_not_called()
        ack.assert_called_once()


if __name__ == '__main__':
    unittest.main()
