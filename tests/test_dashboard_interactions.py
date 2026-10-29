import csv
import io
import unittest
from slack.dashboard_interactions import csv_bytes, selected_outbreak


class DashboardInteractionTests(unittest.TestCase):
    def test_map_uses_object_id_not_index_and_rejects_outside_report(self):
        event = {'selection': {'objects': {'report-outbreaks': [{'outbreak_id': '198839'}]}}}
        self.assertEqual(selected_outbreak(event, {190677, 198839}), 198839)
        self.assertIsNone(selected_outbreak(event, {190677}))
        self.assertIsNone(selected_outbreak({'selection': {'objects': {'report-country': [{}]}}}, {1}))
        self.assertIsNone(selected_outbreak(None, {1}))

    def test_csv_metadata_unicode_zero_missing_and_multiline_roundtrip(self):
        data = csv_bytes([{'축종': 'Mute Swan', '수량': 0, '미보고': None,
                           '원문': '첫 줄, 설명\n두 번째 "줄"'}], {'보고서 ID': 100, '범위': '누계'})
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        row = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))[0]
        self.assertEqual(row['범위'], '누계')
        self.assertEqual(row['수량'], '0')
        self.assertEqual(row['미보고'], '미보고')
        self.assertEqual(row['원문'], '첫 줄, 설명\n두 번째 "줄"')

    def test_text_formulas_are_neutralized_without_changing_negative_numbers(self):
        data = csv_bytes([{'설명': '=1+1', '수량': -3}]).decode('utf-8-sig')
        row = list(csv.DictReader(io.StringIO(data)))[0]
        self.assertEqual(row['설명'], "'=1+1")
        self.assertEqual(row['수량'], '-3')
