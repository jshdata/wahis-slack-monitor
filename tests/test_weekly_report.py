import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from slack.weekly_report import (
    KST, build_weekly_messages, load_weekly_reports, send_weekly_report, weekly_window,
)


class WeeklyReportTests(unittest.TestCase):
    def test_thursday_boundary_and_adjacent_weeks(self):
        start, end = weekly_window(datetime(2026, 10, 22, 9, tzinfo=KST))
        self.assertEqual(start, datetime(2026, 10, 15, 9, tzinfo=KST))
        self.assertEqual(end - start, timedelta(days=7))
        self.assertEqual(weekly_window(end + timedelta(days=7))[0], end)
        self.assertEqual(weekly_window(end - timedelta(seconds=1))[1], start)

    def test_delayed_run_utc_input_and_year_boundary(self):
        self.assertEqual(weekly_window(datetime(2026, 10, 23, 3, tzinfo=timezone.utc))[1],
                         datetime(2026, 10, 22, 9, tzinfo=KST))
        start, end = weekly_window(week_ending='2026-01-01')
        self.assertEqual(start, datetime(2025, 12, 25, 9, tzinfo=KST))
        self.assertEqual(end, datetime(2026, 1, 1, 9, tzinfo=KST))
        with self.assertRaises(ValueError):
            weekly_window(week_ending='2026-10-23')
        with self.assertRaises(ValueError):
            weekly_window(datetime(2026, 10, 22, 9))

    @patch('slack.weekly_report.get_connection')
    def test_query_has_inclusive_start_exclusive_end_in_utc(self, connect):
        connection = MagicMock()
        connect.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        start, end = weekly_window(week_ending='2026-10-22')
        self.assertEqual(load_weekly_reports(start, end), [])
        sql, params = cursor.execute.call_args.args
        self.assertIn('submission_date >= %s AND submission_date < %s', sql)
        self.assertEqual(params, (datetime(2026, 10, 15), datetime(2026, 10, 22)))
        connection.close.assert_called_once()
        cursor.execute.side_effect = RuntimeError('DB unavailable')
        with self.assertRaises(RuntimeError):
            load_weekly_reports(start, end)
        self.assertEqual(connection.close.call_count, 2)

    def reports(self, count):
        return [dict(report_id=i, event_id=7, country='Japan', disease='ASF',
                     submission_date=datetime(2026, 10, 16, 0),
                     report_type=None, reason=None, event_status=None, subtype='A&B',
                     slack_event_json='{"reportType":"Follow-up report",'
                                      '"reason":"First occurrence in the country",'
                                      '"eventStatus":"Ongoing"}') for i in range(count)]

    def test_summary_counts_reasons_links_and_local_time(self):
        start, end = weekly_window(week_ending='2026-10-22')
        text = '\n'.join(build_weekly_messages(self.reports(2), start, end))
        self.assertIn('리포트 2건 · 국가 1개 · 질병 1개 · 이벤트 1개', text)
        self.assertIn('2026-10-22 08:59:59', text)
        self.assertIn('Follow-up report 2건', text)
        self.assertIn('국가/지역 내 첫 발생 2건', text)
        self.assertIn('10-16 09:00', text)
        self.assertIn('A&amp;B', text)
        self.assertIn('?reportId=1&fromPage=event-dashboard-url|Report 1>', text)

    def test_all_reports_survive_slack_chunking_and_empty_week(self):
        start, end = weekly_window(week_ending='2026-10-22')
        messages = build_weekly_messages(self.reports(200), start, end)
        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= 2800 for message in messages))
        text = '\n'.join(messages)
        for i in range(200):
            self.assertEqual(text.count(f'|Report {i}>'), 1)
        self.assertIn('신규 리포트가 없습니다.', build_weekly_messages([], start, end)[0])

    @patch('slack.weekly_report.send_slack_message')
    @patch('slack.weekly_report.load_weekly_reports', return_value=[])
    def test_dry_run_does_not_send_and_empty_week_sends(self, load, send):
        start, end = weekly_window(week_ending='2026-10-22')
        with patch('builtins.print'):
            self.assertEqual(send_weekly_report(start, end, dry_run=True), 0)
        send.assert_not_called()
        send_weekly_report(start, end)
        send.assert_called_once()
        send.side_effect = RuntimeError('Slack unavailable')
        with self.assertRaises(RuntimeError):
            send_weekly_report(start, end)


if __name__ == '__main__':
    unittest.main()
