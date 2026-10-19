import unittest
from unittest.mock import patch

from wahis.api import get_events
from wahis.diseases import DISEASE_NAMES, require_supported_disease, selected_disease_ids
from database.db import insert_disease_report
from database.detail_db import save_report_detail

SCREWWORM = 'Cochliomyia hominivorax (Inf. with) (New world screwworm)'


class DiseaseScopeTests(unittest.TestCase):
    def test_all_target_names_and_trailing_spaces_are_accepted(self):
        for name in DISEASE_NAMES.values():
            require_supported_disease('  ' + name + ' ')
        self.assertEqual(set(selected_disease_ids()), {668, 671, 55, 437, 769, 89})
        with self.assertRaises(ValueError):
            require_supported_disease(SCREWWORM)

    @patch('wahis.api.requests.post')
    def test_empty_or_unknown_filters_cannot_request_all_diseases(self, post):
        for codes in ([], ['SCREWWORM']):
            with self.assertRaises(ValueError):
                get_events(disease_codes=codes)
        post.assert_not_called()

    @patch('wahis.api.requests.post')
    def test_unexpected_server_response_is_not_ingested(self, post):
        post.return_value.json.return_value = {'list': [{'disease': SCREWWORM}]}
        with self.assertRaises(ValueError):
            get_events()

    @patch('database.db.get_connection')
    def test_direct_database_insert_rejects_non_target_before_connecting(self, connect):
        with self.assertRaises(ValueError):
            insert_disease_report({'disease': SCREWWORM})
        connect.assert_not_called()

    @patch('database.detail_db.update_disease_report_detail')
    @patch('database.detail_db.insert_outbreaks')
    @patch('database.detail_db.insert_quantitative_data')
    def test_detail_save_rejects_non_target_before_any_writes(self, quantitative, outbreaks, update):
        with self.assertRaises(ValueError):
            save_report_detail({'report': {'reportId': 1}, 'event': {'disease': {'name': SCREWWORM}}})
        update.assert_not_called()
        outbreaks.assert_not_called()
        quantitative.assert_not_called()

    @patch('database.detail_db.mark_detail_loaded')
    @patch('database.detail_db.insert_quantitative_data')
    @patch('database.detail_db.insert_outbreaks')
    @patch('database.detail_db.update_disease_report_detail')
    def test_target_detail_still_saves_all_parts(self, update, outbreaks, quantitative, mark):
        data = {'report': {'reportId': 1}, 'event': {'disease': {'name': DISEASE_NAMES['BSE'] + ' '}}}
        save_report_detail(data)
        update.assert_called_once_with(data)
        outbreaks.assert_called_once_with(data)
        quantitative.assert_called_once_with(data)
        mark.assert_called_once_with(1)
