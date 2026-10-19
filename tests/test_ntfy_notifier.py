import os
import unittest
from unittest.mock import MagicMock, Mock, patch

import ntfy_notifier as ntfy


class NtfyTests(unittest.TestCase):
    def test_unicode_message_link_and_auth(self):
        event = {'reportId': 123, 'eventId': 456, 'country': '대한민국', 'disease': '질병'}
        with patch.dict(os.environ, {'NTFY_TOKEN': 'test-token'}), patch.object(ntfy.requests, 'post') as post:
            ntfy.send(event, 'https://ntfy.sh/test-topic')
        args, kwargs = post.call_args
        self.assertEqual(args, ('https://ntfy.sh',))
        self.assertEqual(kwargs['json']['topic'], 'test-topic')
        self.assertIn('대한민국', kwargs['json']['message'])
        self.assertIn('reportId=123', kwargs['json']['click'])
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer test-token')
        post.return_value.raise_for_status.assert_called_once()

    def test_disabled_does_not_access_database(self):
        with patch.dict(os.environ, {'NTFY_TOPIC_URL': ''}), patch('database.db.get_connection') as connect:
            ntfy.deliver_pending(Mock())
        connect.assert_not_called()

    def test_failed_channel_does_not_stop_next_report(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(1, '{"reportId": 1}', 'https://ntfy.sh/test'),
                                      (2, '{"reportId": 2}', 'https://ntfy.sh/test')]
        reporter = Mock()
        with patch.dict(os.environ, {'NTFY_TOPIC_URL': 'https://ntfy.sh/test'}), patch('database.db.get_connection', return_value=conn), patch.object(ntfy, 'send', side_effect=[TimeoutError(), None]) as send:
            ntfy.deliver_pending(reporter)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(conn.commit.call_count, 2)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any('attempts = attempts + 1' in sql for sql in statements))
        self.assertTrue(any('sent = 1' in sql for sql in statements))
        reporter.record.assert_called_once()
