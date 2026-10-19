import os
import unittest
from unittest.mock import patch
from database.db import validate_database_settings, get_connection


class DatabaseConfigTests(unittest.TestCase):
    def settings(self):
        return dict(DB_HOST='test', DB_PORT='12345', DB_USER='test',
                    DB_PASSWORD='never-print-this-value', DB_NAME='test')

    @patch('database.db.pymysql.connect')
    def test_missing_settings_are_named_before_any_connection(self, connect):
        with patch.dict(os.environ, {'DB_SSL_CA': 'ca.pem'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME'):
                get_connection()
        connect.assert_not_called()

    def test_invalid_port_is_rejected_without_echoing_value_or_password(self):
        for port in ('secret-invalid-port', '0', '65536'):
            settings = self.settings()
            settings['DB_PORT'] = port
            with patch.dict(os.environ, settings, clear=True):
                with self.assertRaises(ValueError) as caught:
                    validate_database_settings()
            self.assertNotIn('secret-invalid-port', str(caught.exception))
            self.assertNotIn(settings['DB_PASSWORD'], str(caught.exception))

    def test_valid_port(self):
        with patch.dict(os.environ, self.settings(), clear=True):
            self.assertEqual(validate_database_settings(), 12345)
