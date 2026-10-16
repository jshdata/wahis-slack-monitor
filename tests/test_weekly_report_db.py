import unittest
from unittest.mock import MagicMock, patch

from database.weekly_report_db import load_weekly_html, save_weekly_html


class WeeklyStorageTests(unittest.TestCase):
    @patch('database.weekly_report_db.get_connection')
    def test_save_expiration_and_cleanup(self, connect):
        connection = MagicMock()
        connect.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        token = save_weekly_html('<html>weekly</html>')
        self.assertEqual(len(token), 43)
        calls = cursor.execute.call_args_list
        self.assertIn('CREATE TABLE IF NOT EXISTS', calls[0].args[0])
        self.assertIn('DELETE FROM', calls[1].args[0])
        self.assertEqual(calls[2].args[1][:2], (token, '<html>weekly</html>'))
        self.assertEqual((calls[2].args[1][2] - calls[1].args[1][0]).days, 90)
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

    @patch('database.weekly_report_db.get_connection')
    def test_invalid_token_skips_database_and_lookup_checks_expiry(self, connect):
        for token in ('missing', '../' + 'a' * 43, 'a' * 44):
            self.assertIsNone(load_weekly_html(token))
        connect.assert_not_called()
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ('html',)
        self.assertEqual(load_weekly_html('a' * 43), 'html')
        self.assertIn('expires_at > %s', cursor.execute.call_args.args[0])
        cursor.fetchone.return_value = None
        self.assertIsNone(load_weekly_html('a' * 43))

    @patch('database.weekly_report_db.get_connection')
    def test_save_failure_rolls_back_and_closes(self, connect):
        connection = connect.return_value
        connection.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError('DB')
        with self.assertRaises(RuntimeError):
            save_weekly_html('html')
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
