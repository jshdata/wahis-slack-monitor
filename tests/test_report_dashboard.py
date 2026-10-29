import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

from database.report_dashboard_db import load_report_dashboard, valid_coordinates
from slack.report_dashboard_link import report_dashboard_url


class ReportDashboardTests(unittest.TestCase):
    def test_invalid_coordinates_and_zero(self):
        for lat, lon in [(None, 1), (91, 0), (0, -181), ('NaN', 1), (0, 'inf')]:
            self.assertFalse(valid_coordinates(lat, lon))
        self.assertTrue(valid_coordinates(0, 0))

    @patch.dict(os.environ, {'STREAMLIT_DASHBOARD_URL': 'https://example.test/app?x=1&report_id=9'})
    def test_link_preserves_settings_and_replaces_report(self):
        self.assertEqual(report_dashboard_url(123), 'https://example.test/app?x=1&report_id=123')

    @patch.dict(os.environ, {'STREAMLIT_DASHBOARD_URL': ''})
    def test_unconfigured_link_is_absent(self):
        self.assertIsNone(report_dashboard_url(123))

    @patch('database.report_dashboard_db.get_connection')
    def test_report_membership_and_history_do_not_join_followups(self, connect):
        cur = connect.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = {'report_id': 100, 'country': 'Example', 'disease': 'ASF',
                                    'submission_date': datetime(2026, 10, 29)}
        cur.fetchall.side_effect = [[
            {'outbreak_id': 1, 'created_by_report_id': 100, 'latitude': 35, 'longitude': 127},
            {'outbreak_id': 2, 'created_by_report_id': 90, 'latitude': None, 'longitude': 127}],
            [{'day': date(2026, 10, 29), 'count': 3}]]
        result = load_report_dashboard(100, 30)
        self.assertEqual(result['outbreaks'][0]['kind'], '신규')
        self.assertEqual(result['outbreaks'][1]['kind'], '기존 발생 갱신')
        self.assertFalse(result['outbreaks'][1]['mapped'])
        self.assertEqual(len(result['trend']), 30)
        self.assertEqual(sum(r['발생 건수'] for r in result['trend']), 3)
        self.assertIn('EXISTS', cur.execute.call_args.args[0])
        self.assertNotIn('JOIN', cur.execute.call_args.args[0])
        self.assertIn('created_by_report_id=%s OR', cur.execute.call_args_list[1].args[0])
        connect.return_value.close.assert_called_once()

    @patch('database.report_dashboard_db.get_connection')
    def test_missing_report_closes_connection(self, connect):
        connect.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = None
        self.assertIsNone(load_report_dashboard(100))
        connect.return_value.close.assert_called_once()

    @patch('database.report_dashboard_db.get_connection')
    def test_invalid_input_never_queries_database(self, connect):
        with self.assertRaises(ValueError):
            load_report_dashboard(0)
        with self.assertRaises(ValueError):
            load_report_dashboard(100, 7)
        connect.assert_not_called()

    def test_streamlit_screen_with_missing_coordinates_and_species(self):
        from streamlit.testing.v1 import AppTest
        sample = {'report': {'report_id': 100, 'event_id': 10, 'country': 'Example',
                  'disease': 'ASF', 'submission_date': datetime(2026, 10, 29),
                  'report_type': 'Follow-up', 'event_status': 'Ongoing', 'detail_loaded': 0},
                  'outbreaks': [{'outbreak_id': 1, 'kind': '신규', 'mapped': True,
                    'latitude': 35, 'longitude': 127, 'admin_division': 'Region',
                    'location': 'Place', 'location_approx': True, 'start_date': date(2026, 10, 28)},
                    {'outbreak_id': 2, 'kind': '기존 발생 갱신', 'mapped': False,
                    'latitude': None, 'longitude': None, 'admin_division': None,
                    'location': None, 'location_approx': None, 'start_date': None}],
                  'trend': [{'발생일': date(2026, 10, 29), '발생 건수': 1}],
                  'start': date(2026, 10, 1), 'end': date(2026, 10, 29)}
        app = AppTest.from_file('streamlit_app.py', default_timeout=15)
        app.query_params['report_id'] = '100'
        species_sample = {'sites': {1: {'category': '사육', 'species': 'Birds'},
                                    2: {'category': '미확인', 'species': '미확인'}},
                          'categories': {'사육': 1, '야생': 0, '혼합': 0, '미확인': 1},
                          'species': [{'축종': 'Birds', '발생지 수': 1}]}
        with patch('database.report_dashboard_db.load_report_dashboard', return_value=sample), \
             patch('database.report_species_dashboard.load_report_species', return_value=species_sample), \
             patch('database.report_alert_details.get_report_alert_details', return_value={
                 'new_outbreaks': '미확인', 'subtype': '미확인',
                 'animal_category': '미확인', 'species': '미확인'}):
            app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.metric[0].value, '미확인')
        self.assertEqual(len(app.warning), 1)
        self.assertTrue(any('2곳 중' in c.value and '1곳 표시' in c.value for c in app.caption))
        self.assertEqual(app.metric[2].value, '1건')
        self.assertEqual([m.value for m in app.metric[3:]], ['1곳', '0곳', '0곳', '1곳'])
        for counts in ([0, 0], [2, 3]):
            sample['trend'] = [{'발생일': date(2026, 10, 28 + i), '발생 건수': count}
                               for i, count in enumerate(counts)]
            with patch('database.report_dashboard_db.load_report_dashboard', return_value=sample), \
                 patch('database.report_species_dashboard.load_report_species', return_value=species_sample), \
                 patch('database.report_alert_details.get_report_alert_details', return_value={
                     'new_outbreaks': '미확인', 'subtype': '미확인',
                     'animal_category': '미확인', 'species': '미확인'}):
                app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.metric[2].value, f'{sum(counts)}건')
            if not sum(counts):
                self.assertTrue(any('DB에서 확인되는 발생이 없습니다' in info.value for info in app.info))

    def test_streamlit_requires_report_link(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file('streamlit_app.py', default_timeout=15).run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn('대시보드 버튼', app.info[0].value)
