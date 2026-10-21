import unittest
from unittest.mock import patch

from database import report_alert_details as details
from slack import notifier


class ReportAlertDetailsTests(unittest.TestCase):
    @patch.object(details, 'get_connection')
    def test_both_categories_and_species_are_read_from_outbreaks(self, connect):
        cur = connect.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = ('H5N1',)
        cur.fetchall.return_value = [(1, 100, 'Birds', 0), (2, 100, 'Mallard', 1),
                                     (2, 100, 'Mallard', 1)]
        result = details.get_report_alert_details({'reportId': 100})
        self.assertEqual(result['subtype'], 'H5N1')
        self.assertEqual(result['animal_category'], '사육 / 야생')
        self.assertEqual(result['species'], 'Birds (사육), Mallard (야생)')
        self.assertNotIn('report_quantitative', cur.execute.call_args.args[0])
        self.assertEqual(cur.execute.call_args.args[1], (100, 100))

    @patch.object(details, 'get_connection')
    def test_incomplete_species_are_not_presented_as_domestic(self, connect):
        cur = connect.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (None,)
        cur.fetchall.return_value = [(1, 99, 'Cattle', 0), (2, 100, 'Birds', 0)]
        result = details.get_report_alert_details({'reportId': 100})
        self.assertEqual(result['animal_category'], '사육 / 미확인 포함')
        self.assertNotIn('Cattle', result['species'])
        self.assertEqual(result['subtype'], '미확인')

    @patch.object(details, 'get_connection', side_effect=RuntimeError('DB unavailable'))
    def test_lookup_failure_keeps_notification_usable(self, connect):
        result = details.get_report_alert_details({'reportId': 100})
        self.assertEqual(set(result.values()), {'미확인'})

    @patch.object(details, 'get_connection')
    def test_species_list_is_bounded_and_null_is_unknown(self, connect):
        cur = connect.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = ('O',)
        cur.fetchall.return_value = [(i, 100, f'Species {i:02}', None) for i in range(20)]
        result = details.get_report_alert_details({'reportId': 100})
        self.assertEqual(result['animal_category'], '미확인')
        self.assertIn('외 10종', result['species'])

    @patch('apqa.matcher.analyze_apqa', return_value={'priority': 'NORMAL'})
    @patch.object(notifier, 'get_report_alert_details', return_value={
        'subtype': 'SAT 1', 'animal_category': '사육', 'species': 'Cattle (사육)'})
    @patch.object(notifier, 'send_slack_message')
    def test_slack_contains_subtype_category_and_species(self, send, lookup, apqa):
        notifier.send_new_report_alert({'reportId': 100, 'eventId': 10,
                                        'country': 'Example', 'disease': 'FMD'})
        text = str(send.call_args.kwargs['blocks'])
        for value in ['SAT 1', '사육', 'Cattle', '축종']:
            self.assertIn(value, text)


if __name__ == '__main__':
    unittest.main()
