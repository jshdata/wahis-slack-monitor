import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from database.weekly_delivery import WeeklyDelivery
from slack.weekly_report import KST, send_weekly_report, weekly_window
from weekly_main import main, scheduled_window


class WeeklyScheduleTests(unittest.TestCase):
    def test_seoul_thursday_boundary_and_utc(self):
        self.assertIsNone(scheduled_window(datetime(2026, 11, 12, 8, 59, tzinfo=KST)))
        window = scheduled_window(datetime(2026, 11, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(window[1], datetime(2026, 11, 12, 9, tzinfo=KST))
        self.assertEqual(scheduled_window(datetime(2026, 11, 12, 23, 59, tzinfo=KST)), window)
        self.assertIsNone(scheduled_window(datetime(2026, 11, 11, 10, tzinfo=KST)))
        self.assertIsNone(scheduled_window(datetime(2026, 11, 13, 10, tzinfo=KST)))
        with self.assertRaises(ValueError):
            scheduled_window(datetime(2026, 11, 12, 9))

    def test_rollout_does_not_repeat_todays_existing_digest(self):
        self.assertIsNone(scheduled_window(datetime(2026, 11, 5, 14, tzinfo=KST), '2026-11-12'))
        self.assertIsNotNone(scheduled_window(datetime(2026, 11, 12, 9, tzinfo=KST), '2026-11-12'))
        self.assertIsNotNone(scheduled_window(datetime(2026, 11, 19, 9, tzinfo=KST), '2026-11-12'))

    @patch('weekly_main.send_weekly_report')
    @patch('weekly_main.scheduled_window', return_value=None)
    def test_not_due_skips_database_and_notification(self, window, send):
        with patch.object(sys, 'argv', ['weekly_main.py', '--scheduled']), patch('builtins.print'):
            main()
        send.assert_not_called()

    @patch('weekly_main.send_weekly_report', return_value=0)
    def test_manual_defaults_to_once_and_force_is_explicit(self, send):
        with patch.object(sys, 'argv', ['weekly_main.py', '--week-ending', '2026-11-12']), patch('builtins.print'):
            main()
        self.assertTrue(send.call_args.kwargs['once'])
        with patch.object(sys, 'argv', ['weekly_main.py', '--week-ending', '2026-11-12', '--force']), patch('builtins.print'):
            main()
        self.assertFalse(send.call_args.kwargs['once'])

    @patch('slack.weekly_report.weekly_delivery')
    @patch('slack.weekly_report.load_weekly_reports')
    @patch('slack.weekly_report.send_slack_message')
    def test_already_sent_skips_query_and_send(self, send, load, guard):
        guard.return_value.__enter__.return_value.ready = False
        start, end = weekly_window(week_ending='2026-11-12')
        with patch('builtins.print'):
            self.assertEqual(send_weekly_report(start, end, once=True), 0)
        load.assert_not_called()
        send.assert_not_called()

    @patch('slack.weekly_report.weekly_delivery')
    @patch('slack.weekly_report.save_weekly_html', return_value='a' * 43)
    @patch('slack.weekly_report.load_weekly_reports', return_value=[])
    @patch('slack.weekly_report.send_slack_message')
    def test_claim_precedes_send_and_success_is_recorded(self, send, load, save, guard):
        delivery = guard.return_value.__enter__.return_value
        delivery.ready = True
        order = []
        delivery.begin_send.side_effect = lambda: order.append('claimed')
        send.side_effect = lambda *a, **k: order.append('sent')
        delivery.mark_sent.side_effect = lambda: order.append('recorded')
        start, end = weekly_window(week_ending='2026-11-12')
        send_weekly_report(start, end, once=True)
        self.assertEqual(order, ['claimed', 'sent', 'recorded'])
        guard.reset_mock()
        with patch('builtins.print'):
            send_weekly_report(start, end, dry_run=True, once=True)
        guard.assert_not_called()


class WeeklyDeliveryTests(unittest.TestCase):
    def connection(self, lock=1, status=None):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [(lock,), (status,) if status else None]
        return connection, cursor

    @patch('database.weekly_delivery.get_connection')
    def test_completed_or_uncertain_weeks_are_never_automatically_retried(self, connect):
        for status in ['sent', 'sending', 'uncertain']:
            with self.subTest(status=status):
                connection, cursor = self.connection(status=status)
                connect.return_value = connection
                with WeeklyDelivery(datetime(2026, 11, 12, 9, tzinfo=KST)) as delivery:
                    self.assertFalse(delivery.ready)
                self.assertFalse(any('INSERT INTO' in c.args[0] for c in cursor.execute.call_args_list))
                self.assertTrue(any('RELEASE_LOCK' in c.args[0] for c in cursor.execute.call_args_list))
                connection.close.assert_called_once()

    @patch('database.weekly_delivery.get_connection')
    def test_other_runner_holding_week_lock_skips(self, connect):
        connection, cursor = self.connection(lock=0)
        connect.return_value = connection
        with WeeklyDelivery(datetime(2026, 11, 12, 9, tzinfo=KST)) as delivery:
            self.assertFalse(delivery.ready)
            self.assertEqual(delivery.status, 'busy')
        self.assertFalse(any('SELECT status' in c.args[0] for c in cursor.execute.call_args_list))

    @patch('database.weekly_delivery.get_connection')
    def test_success_and_ambiguous_send_failure_are_persisted(self, connect):
        connection, cursor = self.connection()
        connect.return_value = connection
        with WeeklyDelivery(datetime(2026, 11, 12, 9, tzinfo=KST)) as delivery:
            self.assertTrue(delivery.ready)
            delivery.begin_send()
            delivery.mark_sent()
        self.assertTrue(any("status = 'sent'" in c.args[0] for c in cursor.execute.call_args_list))
        self.assertFalse(any("status = 'uncertain'" in c.args[0] for c in cursor.execute.call_args_list))
        connection, cursor = self.connection()
        connect.return_value = connection
        with self.assertRaisesRegex(RuntimeError, 'response lost'):
            with WeeklyDelivery(datetime(2026, 11, 12, 9, tzinfo=KST)) as delivery:
                delivery.begin_send()
                raise RuntimeError('response lost')
        self.assertTrue(any("status = 'uncertain'" in c.args[0] for c in cursor.execute.call_args_list))
        connection.close.assert_called_once()

    @patch('database.weekly_delivery.get_connection')
    def test_failure_before_send_does_not_claim_delivery(self, connect):
        connection, cursor = self.connection()
        connect.return_value = connection
        with self.assertRaises(RuntimeError):
            with WeeklyDelivery(datetime(2026, 11, 12, 9, tzinfo=KST)):
                raise RuntimeError('HTML generation failed')
        self.assertFalse(any('INSERT INTO' in c.args[0] for c in cursor.execute.call_args_list))
        connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
