import unittest
from unittest.mock import patch, MagicMock

from slack.control_measures_report import build_report
from slack.control_measures_app import result_view, register_control_handlers


class ControlReportTests(unittest.TestCase):
    @patch('slack.control_measures_report.control_storage.query')
    def test_report_contains_filters_and_escapes_rows_with_pagination(self, query):
        row = dict(year=2026, semester='Jan-Jun 2026', region='Asia', country='<script>alert(1)</script>',
                   disease='poultry', category='Domestic', species='Birds', measure='Official vaccination')
        query.return_value = {'total': 734, 'page': 1, 'rows': [row], 'snapshot_at': '2026-10-19'}
        filters = {'disease': 'HPAI', 'year': '2026', 'scope': 'official'}
        html = build_report(filters, {'page': ['1']})
        query.assert_called_once_with(filters, 1, page_size=100)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('734', html)
        self.assertIn('?page=2', html)
        self.assertIn('공식 예방접종만', html)

    @patch('slack.control_measures_report.control_storage.query')
    def test_invalid_page_and_empty_report(self, query):
        query.return_value = {'total': 0, 'page': 0, 'rows': [], 'snapshot_at': None}
        html = build_report({'disease': 'ASF'}, {'page': ['bad']})
        self.assertEqual(query.call_args.args[1], 0)
        self.assertIn('해당 조건의 보고 항목이 없습니다', html)

    @patch('slack.control_measures_app.control_storage.query')
    def test_modal_provides_html_action_and_ready_link(self, query):
        query.return_value = {'total': 0, 'page': 0, 'rows': [], 'snapshot_at': None}
        filters = {'disease': 'ASF'}
        first = result_view(filters)
        self.assertIn('control_html', str(first))
        ready = result_view(filters, html_url='https://example.test/reports/token')
        links = [e for b in ready['blocks'] for e in b.get('elements', []) if 'url' in e]
        self.assertEqual(links[0]['url'], 'https://example.test/reports/token')

    @patch('slack.control_measures_app.report_url', return_value='https://example.test/reports/token')
    @patch('slack.control_measures_app.submit')
    @patch('slack.control_measures_app.result_view')
    @patch('slack.control_measures_app.build_report', return_value='rendered')
    def test_html_action_registers_lazy_renderer_with_same_filters(self, build, result, submit, url):
        import json
        handlers = {}
        app = MagicMock()
        def register(action):
            def decorator(fn):
                handlers[action] = fn
                return fn
            return decorator
        app.action.side_effect = register
        reports = {}
        register_control_handlers(app, reports)
        filters = {'disease': 'HPAI', 'year': '2026', 'country': 'Japan'}
        body = {'view': {'id': 'V1'}, 'actions': [{'value': json.dumps({'filters': filters, 'page': 2})}]}
        handlers['control_html'](MagicMock(), body, MagicMock())
        submit.call_args.args[2]()
        build.assert_not_called()
        report = next(iter(reports.values()))
        self.assertEqual(report['render']({'page': ['3']}), 'rendered')
        build.assert_called_once_with(filters, {'page': ['3']})
