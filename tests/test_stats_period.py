import ast
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from database import stats_db


class StatsPeriodTests(unittest.TestCase):
    def resolver(self, bounds):
        source = ast.parse(Path('slack/query_app.py').read_text(encoding='utf-8'))
        node = next(n for n in source.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'resolve_stats_period')
        query = Mock(return_value=bounds)
        namespace = {'get_outbreak_date_bounds': query, 'datetime': datetime}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<period>', 'exec'), namespace)
        return namespace['resolve_stats_period'], query

    def test_default_uses_entire_selected_data_range(self):
        resolve, query = self.resolver(('2014-01-01', '2026-10-15'))
        self.assertEqual(resolve('HPAI', None, None, 'Asia', 'Japan'),
                         ('2014-01-01', '2026-10-15'))
        query.assert_called_once_with('HPAI', region='Asia', country='Japan')

    def test_one_sided_dates_and_explicit_range(self):
        resolve, query = self.resolver(('2014-01-01', '2026-10-15'))
        self.assertEqual(resolve('ASF', '2025-01-01', None), ('2025-01-01', '2026-10-15'))
        self.assertEqual(resolve('ASF', None, '2025-12-31'), ('2014-01-01', '2025-12-31'))
        query.reset_mock()
        self.assertEqual(resolve('ASF', '2020-01-01', '2021-01-01'), ('2020-01-01', '2021-01-01'))
        query.assert_not_called()

    def test_outside_data_and_empty_results_have_valid_bounds(self):
        resolve, _ = self.resolver(('2014-01-01', '2026-10-15'))
        self.assertEqual(resolve('ASF', '2030-01-01', None), ('2030-01-01', '2030-01-01'))
        self.assertEqual(resolve('ASF', None, '2000-01-01'), ('2000-01-01', '2000-01-01'))
        resolve, _ = self.resolver((None, None))
        start, end = resolve('ASF', None, None)
        self.assertEqual(start, end)
        date.fromisoformat(start)

    def test_hpai_bounds_include_poultry_and_non_poultry(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (date(2014, 1, 1), date(2026, 10, 15))
        with patch.object(stats_db, 'get_connection', return_value=connection):
            self.assertEqual(stats_db.get_outbreak_date_bounds('HPAI', region='America'),
                             ('2014-01-01', '2026-10-15'))
        sql, params = cursor.execute.call_args.args
        self.assertEqual(params[:2], [stats_db.DISEASE_MAP['HPAI'], stats_db.DISEASE_MAP['HPAI_NON_POULTRY']])
        self.assertEqual(params[2:], ['North America', 'South America'])
        self.assertIn('MIN(o.start_date)', sql)
        connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
