import ast
from datetime import datetime, date
from pathlib import Path
import unittest
from unittest.mock import MagicMock, Mock, patch

from database import query_db, stats_db
from database.filters import selection_value, selection_values, selection_label
from database.regions import region_filter
from database.presence_db import disease_codes
from slack.multi_filters import selected_value, selected_values, multi_filter_view
from slack.presence_app import settings_view
from slack.filter_state import encode_filters, decode_filters
from slack.woah_docs import list_view, countries_view


def load_query_functions(names, namespace=None):
    tree = ast.parse(Path('slack/query_app.py').read_text(encoding='utf-8'))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in names for target in node.targets):
            nodes.append(node)
    scope = {'datetime': datetime, 'selected_value': selected_value,
             'selected_values': selected_values, 'selection_values': selection_values,
             'selection_value': selection_value, 'selection_label': selection_label,
             'multi_filter_view': multi_filter_view, **(namespace or {})}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<multi-filter-query>', 'exec'), scope)
    return scope


class MultiFilterTests(unittest.TestCase):
    def test_large_country_filters_survive_button_limits_and_expire_cleanly(self):
        params = {'k': [f'Country {i:03} long name' for i in range(200)], 'page': 3}
        with patch('slack.filter_state.time.time', return_value=100):
            packed = encode_filters(params)
            self.assertLess(len(packed), 2000)
            self.assertEqual(decode_filters(packed), params)
        with patch('slack.filter_state.time.time', return_value=3701):
            with self.assertRaises(ValueError):
                decode_filters(packed)
        self.assertEqual(decode_filters(encode_filters({'k': ['Japan', 'Germany']})),
                         {'k': ['Japan', 'Germany']})

    def test_empty_multi_and_legacy_state(self):
        self.assertEqual(selected_value({'selected_options': None}), 'all')
        self.assertEqual(selected_value({'selected_option': {'value': 'Japan'}}), 'Japan')
        self.assertEqual(selected_value({'selected_options': [{'value': 'Japan'}, {'value': 'Germany'}]}),
                         ['Japan', 'Germany'])
        self.assertEqual(selection_label(['Asia', 'Europe']), 'Asia, Europe')

    def test_country_and_region_filters_are_parameterized_and_intersect(self):
        for function in (stats_db.get_outbreak_stats, stats_db.get_outbreak_duration_stats,
                         stats_db.get_outbreak_events):
            conn = MagicMock()
            with patch.object(stats_db, 'get_connection', return_value=conn):
                function('ASF', '2023-01-01', '2025-12-31',
                         region=['Asia', 'Europe'], country=['Japan', "Germany' OR 1=1"])
            sql, values = conn.cursor.return_value.__enter__.return_value.execute.call_args.args
            self.assertIn('dr.country IN (%s, %s)', sql)
            self.assertIn('(cr.region = %s OR cr.region = %s)', sql)
            self.assertNotIn("Germany' OR 1=1", sql)
            self.assertIn("Germany' OR 1=1", values)

    @patch('database.query_db.get_connection')
    def test_report_search_multiple_diseases_expand_hpai_once(self, connect):
        query_db.search_reports(disease=['HPAI', 'ASF'], country=['Japan', 'Germany'],
                                region=['Asia', 'Europe'])
        sql, params = connect.return_value.cursor.return_value.execute.call_args.args
        self.assertIn('dr.country IN (%s, %s)', sql)
        self.assertIn('dr.disease IN (%s, %s, %s)', sql)
        for name in query_db.DISEASE_MAP['HPAI'] + query_db.DISEASE_MAP['ASF']:
            self.assertEqual(params.count(name), 1)

    def test_view_builders_convert_filters_but_keep_output_modes_single(self):
        names = {'build_search_modal', 'build_stats_modal', 'build_country_select_options',
                 'REGION_OPTIONS', 'ANIMAL_OPTIONS', 'DISEASE_OPTIONS',
                 'STATS_DISEASE_OPTIONS', 'STATS_VIEW_OPTIONS'}
        options = [{'text': {'type': 'plain_text', 'text': 'all'}, 'value': 'all'}]
        scope = load_query_functions(names, {'build_country_options': lambda: options})
        for name in ('build_search_modal', 'build_stats_modal'):
            view = scope[name]()
            if name == 'build_stats_modal':
                rows = [b['elements'] for b in view['blocks'] if b['type'] == 'actions']
                self.assertEqual([len(row) for row in rows], [2, 2, 2, 2])
                self.assertEqual(len({e['action_id'] for row in rows for e in row}), 8)
                self.assertIn('woah_countries_open', {e['action_id'] for row in rows for e in row})
            for block in view['blocks']:
                element = block.get('element', {})
                action = element.get('action_id', '')
                if 'country_select' in action:
                    self.assertEqual(element['type'], 'multi_external_select')
                    self.assertTrue(block['optional'])
                elif action in ('region_select', 'animal_select', 'disease_select',
                                'stats_region_select', 'stats_disease_select'):
                    self.assertEqual(element['type'], 'multi_static_select')
                elif action == 'stats_view_select':
                    self.assertEqual(element['type'], 'static_select')

    def test_multi_disease_stats_share_one_collector_and_one_result_modal(self):
        collect, show = Mock(), Mock()
        scope = load_query_functions({'handle_wahis_stats_search', 'parse_stats_date'}, {
            'StatsModalCollector': Mock(), 'collect_disease_stats': collect,
            'show_stats_result_modal': show,
            'resolve_stats_period': Mock(return_value=('2023-01-01', '2025-12-31'))})
        values = {}
        for field, choices in [('disease', ['ASF', 'FMD']), ('country', ['Japan', 'Germany']),
                               ('region', ['Asia', 'Europe'])]:
            values[f'stats_{field}_block'] = {f'stats_{field}_select': {
                'selected_options': [{'value': item} for item in choices]}}
        values['stats_view_block'] = {'stats_view_select': {'selected_option': {'value': 'duration'}}}
        scope['handle_wahis_stats_search'](Mock(), {'view': {'id': 'V1'}},
                                           {'state': {'values': values}}, MagicMock())
        self.assertEqual(collect.call_count, 2)
        self.assertEqual([call.args[2] for call in collect.call_args_list], ['ASF', 'FMD'])
        self.assertEqual(collect.call_args.args[6], ['Japan', 'Germany'])
        show.assert_called_once()

    def test_country_suggestions_search_beyond_first_hundred(self):
        query = Mock(return_value=[f'Country {i:03}' for i in range(230)])
        scope = load_query_functions({'suggest_countries'}, {'get_countries': query})
        ack = Mock()
        scope['suggest_countries'](ack, {'action_id': 'stats_country_select', 'value': '229',
            'view': {'state': {'values': {'stats_region_block': {'stats_region_select': {
                'selected_options': [{'value': 'Asia'}, {'value': 'Europe'}]}}}}}})
        query.assert_called_once_with(['Asia', 'Europe'])
        self.assertEqual(ack.call_args.kwargs['options'][0]['value'], 'Country 229')

    def test_presence_and_region_union(self):
        self.assertEqual(disease_codes(['HPAI', 'ASF']), ['HPAI', 'HPAI_NON_POULTRY', 'ASF'])
        view = settings_view(['ASF', 'FMD'])
        self.assertEqual([option['value'] for option in view['blocks'][1]['element']['initial_options']],
                         ['ASF', 'FMD'])
        condition, values = region_filter(['America', 'Other'])
        self.assertIn('IS NULL', condition)
        self.assertEqual(values[:2], ['North America', 'South America'])

    @patch('slack.woah_docs.woah_db')
    def test_woah_multiple_diseases_exclude_unselected_docs(self, db):
        docs = [dict(disease=code, country='Japan', region='Asia', published_date=None)
                for code in ('HPAI', 'ASF', 'FMD')]
        db.list_declaration_countries.return_value = docs
        view = countries_view(['HPAI', 'ASF'])
        text = str(view)
        self.assertIn('*HPAI*', text)
        self.assertIn('*ASF*', text)
        self.assertNotIn('*FMD*', text)


if __name__ == '__main__':
    unittest.main()
