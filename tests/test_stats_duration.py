import ast
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock


class YearlyDurationTests(unittest.TestCase):
    def setUp(self):
        source = ast.parse(Path('slack/query_app.py').read_text(encoding='utf-8'))
        names = {'build_yearly_duration_messages', 'build_duration_messages'}
        nodes = [node for node in source.body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
        self.query = Mock(return_value=[('Japan', 'Asia', 1, 1, 28)])
        namespace = {'datetime': datetime, 'get_outbreak_duration_stats': self.query}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<duration>', 'exec'), namespace)
        self.render = namespace['build_yearly_duration_messages']

    def messages(self, start, end):
        return list(self.render('ASF', 'ASF', 'Asia', 'Japan', start, end, 28,
                                region='Asia', country='Japan'))

    def test_three_years_and_leap_year_ratio(self):
        messages = self.messages('2023-01-01', '2025-12-31')
        self.assertEqual(len(messages), 3)
        for message, year, days in zip(messages, (2023, 2024, 2025), (365, 366, 365)):
            self.assertIn(f'{year}-01-01 ~ {year}-12-31 ({days}일)', message)
            self.assertIn(f'{28 / days * 100:.1f}%', message)
        self.assertEqual(self.query.call_count, 3)

    def test_partial_years_and_single_year(self):
        messages = self.messages('2023-12-20', '2024-01-10')
        self.assertIn('2023-12-20 ~ 2023-12-31 (12일)', messages[0])
        self.assertIn('2024-01-01 ~ 2024-01-10 (10일)', messages[1])
        self.query.reset_mock()
        self.assertEqual(len(self.messages('2024-06-01', '2024-06-30')), 1)
        self.assertEqual(self.query.call_args.kwargs['start_date'], '2024-06-01')
        self.assertEqual(self.query.call_args.kwargs['end_date'], '2024-06-30')

    def test_ten_years_with_empty_results_preserve_filters(self):
        self.query.return_value = []
        messages = self.messages('2016-01-01', '2025-12-31')
        self.assertEqual(len(messages), 10)
        for year, call in zip(range(2016, 2026), self.query.call_args_list):
            self.assertEqual(call.kwargs, dict(
                disease_code='ASF', start_date=f'{year}-01-01',
                end_date=f'{year}-12-31', region='Asia', country='Japan', gap_days=28))
        self.assertTrue(all('조회된 outbreak가 없습니다.' in message for message in messages))

    def test_html_rows_share_annual_calculation_and_keep_full_country_names(self):
        name = 'A country name longer than twenty six characters'
        self.query.return_value = [(name, 'Asia', 7, 2, 60)]
        items = []
        list(self.render('ASF', 'ASF', 'Asia', '전체', '2023-01-01', '2025-12-31', 28,
                         report_items=items))
        self.assertEqual(self.query.call_count, 3)
        self.assertEqual([item['year'] for item in items], [2023, 2024, 2025])
        self.assertEqual(items[1]['rows'][0], (name, 'Asia', 7, 2, 60))


class DurationHtmlTests(unittest.TestCase):
    def test_duration_result_modal_has_html_link_using_already_computed_rows(self):
        import json
        import time
        from types import SimpleNamespace
        from slack.duration_report import build_duration_report
        source = ast.parse(Path('slack/query_app.py').read_text(encoding='utf-8'))
        names = {'StatsModalCollector', '_stats_modal_pages', '_stats_text_chunks',
                 '_matrix_table_chunks', 'build_stats_result_modal', 'show_stats_result_modal'}
        nodes = [n for n in source.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
        scope = {'json': json, 'time': time, 'uuid4': lambda: SimpleNamespace(hex='test'),
                 '_STATS_MODAL_RESULTS': {}, '_STATS_MATRIX_REPORTS': {}, 'REPORT_TTL_SECONDS': 3600,
                 'report_url': lambda key: 'https://example.test/reports/' + key,
                 'build_duration_report': build_duration_report}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<duration-modal>', 'exec'), scope)
        collector = scope['StatsModalCollector']()
        collector.items = [{'kind': 'text', 'text': 'Annual durations'}]
        collector.duration_items = self.items()
        client = Mock()
        scope['show_stats_result_modal'](client, {'view': {'id': 'V1'}}, collector)
        view = client.views_update.call_args.kwargs['view']
        links = [e for b in view['blocks'] for e in b.get('elements', []) if e.get('url')]
        self.assertEqual(links[0]['text']['text'], 'HTML 표 보기')
        self.assertIn('2025', scope['_STATS_MATRIX_REPORTS']['test']['html'])

    def items(self):
        return [dict(year=year, disease=disease, region_label='전체', country_label='전체',
                     start_date=f'{year}-01-01', end_date=f'{year}-12-31', gap_days=28,
                     rows=[('United States of America <test>', 'America', 12, 3, 28)])
                for disease in ('HPAI 가금', 'HPAI 가금 외') for year in (2023, 2024, 2025)]

    def test_all_years_scopes_and_leap_year_ratios_are_copyable(self):
        from slack.duration_report import build_duration_report
        html = build_duration_report(self.items())
        self.assertEqual(html.count('<tr>'), 7)
        self.assertIn('United States of America &lt;test&gt;', html)
        self.assertNotIn('America <test>', html)
        self.assertIn('<td>366</td>', html)
        self.assertIn('HPAI 가금 외', html)
        self.assertIn('navigator.clipboard.writeText(tsv())', html)
        self.assertIn('wahis-yearly-observation.tsv', html)
        self.assertIn(r"join('\t')", html)

    def test_empty_result_and_partial_year_denominator(self):
        from slack.duration_report import build_duration_report
        items = self.items()[:1]
        items[0].update(start_date='2023-12-20', end_date='2023-12-31',
                        rows=[('Japan', 'Asia', 1, 1, 10)])
        self.assertIn('<td>83.3</td>', build_duration_report(items))
        items[0]['rows'] = []
        self.assertIn('조회 결과가 없습니다', build_duration_report(items))


if __name__ == '__main__':
    unittest.main()
