import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from database import query_db, stats_db
from database.regions import KNOWN_REGIONS, region_filter
from slack.stats_report import build_matrix_report


def load_renderers():
    # Avoid constructing the Slack client or making authentication requests.
    source = ast.parse(Path('slack/query_app.py').read_text(encoding='utf-8'))
    names = {'build_matrix_text', 'post_matrix_message', 'StatsModalCollector',
             '_matrix_table_chunks', '_stats_modal_pages', '_stats_text_chunks',
             'matrix_report_rows'}
    nodes = [n for n in source.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and n.name in names]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<renderers>', 'exec'), namespace)
    return namespace


class MatrixTests(unittest.TestCase):
    def test_all_columns_and_totals_survive_modal_rendering(self):
        render = load_renderers()
        rows = [('Long country name', 'Asia', f'H5N{i}', i + 1) for i in range(19)]
        rows += [('USA', 'North America', 'H5N1', 3),
                 ('Brazil', 'South America', 'H5N1', 4),
                 ('Unknown', None, 'H5N1', 1)]
        result = stats_db.build_matrix(rows)
        self.assertEqual(result['region_totals']['America'], 7)
        self.assertEqual(result['region_totals']['Other'], 1)
        collector = render['StatsModalCollector']()
        text = render['build_matrix_text'](result, 'HPAI', 'All', 'All', '2020-01-01', '2026-10-15')
        render['post_matrix_message'](collector, 'unused', text, result=result)
        self.assertEqual(len(collector.items), 1)
        table = collector.items[0]['table']
        header = table.splitlines()[0]
        for subtype in result['subtypes']:
            self.assertIn(subtype, header)
        self.assertTrue(header.endswith('Total'))
        self.assertIn('Long country name', table)
        self.assertNotIn('[REGION_', table)
        for row in table.splitlines():
            self.assertEqual(len(row), len(header))
        blocks = render['_stats_modal_pages'](collector.items)[0]
        self.assertEqual(sum(b['type'] == 'rich_text' for b in blocks), 1)
        report = build_matrix_report(collector.items)
        self.assertEqual(report.count('<col style='), 21)
        self.assertEqual(report.count('width:4.76190476%'), 21)
        self.assertIn('table-layout: fixed', report)
        self.assertIn('overflow: auto', report)
        self.assertIn('Long country name', report)
        self.assertIn('<th scope="col">Total</th>', report)
        self.assertIn('requestFullscreen()', report)

    def test_html_report_escapes_data(self):
        html = build_matrix_report([{'kind': 'matrix', 'text': '<script>bad</script>',
                                    'rows': [['Country', 'Total'], ['<img>', 1]]}])
        self.assertNotIn('<script>bad', html)
        self.assertIn('&lt;img&gt;', html)
        self.assertEqual(html.count('width:50.00000000%'), 2)

    def test_large_tables_split_rows_without_losing_columns(self):
        render = load_renderers()
        table = 'Country H5N1 H5N2 Total\n----------------------\n' + '\n'.join(
            f'Country{i:03} 1 2 3' for i in range(240))
        chunks = list(render['_matrix_table_chunks'](table, limit=200))
        recovered = []
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 200)
            self.assertEqual(chunk.splitlines()[:2], table.splitlines()[:2])
            recovered.extend(chunk.splitlines()[2:])
        self.assertEqual(recovered, table.splitlines()[2:])

    def test_other_includes_missing_and_unrecognized_regions(self):
        condition, params = region_filter('Other')
        self.assertIn('IS NULL', condition)
        self.assertIn('NOT IN', condition)
        self.assertEqual(params, list(KNOWN_REGIONS))
        for function in (stats_db.get_outbreak_stats, stats_db.get_outbreak_duration_stats,
                         stats_db.get_outbreak_events):
            connection = MagicMock()
            cursor = connection.cursor.return_value.__enter__.return_value
            with patch.object(stats_db, 'get_connection', return_value=connection):
                function('ASF', '2020-01-01', '2026-10-15', region='Other')
            sql, values = cursor.execute.call_args.args
            self.assertIn(condition, sql)
            self.assertEqual(values[1:7], list(KNOWN_REGIONS))
        connection = MagicMock()
        with patch.object(query_db, 'get_connection', return_value=connection):
            query_db.get_countries('Other')
        sql, values = connection.cursor.return_value.execute.call_args.args
        self.assertIn('UNION', sql)
        self.assertIn('LEFT JOIN', sql)
        self.assertIn(condition, sql)
        self.assertEqual(values, list(KNOWN_REGIONS))


if __name__ == '__main__':
    unittest.main()
