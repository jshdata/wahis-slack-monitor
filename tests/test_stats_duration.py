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


if __name__ == '__main__':
    unittest.main()
