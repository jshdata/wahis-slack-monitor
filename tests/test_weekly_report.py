import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from slack.weekly_report import (
    KST, build_weekly_messages, load_weekly_reports, send_weekly_report, weekly_window,
    report_kind,
)
from slack.weekly_html import build_weekly_html


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
                     detail_loaded=1, new_outbreak_count=2,
                     slack_event_json='{"reportType":"Follow-up report",'
                                      '"reason":"First occurrence in the country",'
                                      '"eventStatus":"Ongoing"}') for i in range(count)]

    def test_summary_counts_reasons_links_and_local_time(self):
        start, end = weekly_window(week_ending='2026-10-22')
        text = build_weekly_messages(self.reports(2), start, end)[0]
        self.assertIn('리포트 2건', text)
        self.assertIn('후속 리포트 2건 · 추가 발생 4건', text)
        self.assertNotIn('Report 1', text)
        text = build_weekly_html(self.reports(2), start, end)
        self.assertIn('2026.10.22 08:59', text)
        self.assertIn('Follow-up report', text)
        self.assertIn('국가/지역 내 첫 발생', text)
        self.assertIn('10-16 09:00', text)
        self.assertIn('A&amp;B', text)
        self.assertIn('?reportId=1&amp;fromPage=event-dashboard-url', text)

    def test_all_reports_survive_slack_chunking_and_empty_week(self):
        start, end = weekly_window(week_ending='2026-10-22')
        messages = build_weekly_messages(self.reports(200), start, end)
        self.assertEqual(len(messages), 1)
        self.assertTrue(all(len(message) <= 2800 for message in messages))
        text = build_weekly_html(self.reports(200), start, end)
        for i in range(200):
            self.assertEqual(text.count(f'Report {i} ↗'), 3)
        self.assertIn('신규 리포트가 없습니다.', build_weekly_messages([], start, end)[0])

    @patch('slack.weekly_report.save_weekly_html', return_value='a' * 43)
    @patch('slack.weekly_report.send_slack_message')
    @patch('slack.weekly_report.load_weekly_reports', return_value=[])
    def test_dry_run_does_not_send_and_empty_week_sends(self, load, send, save):
        start, end = weekly_window(week_ending='2026-10-22')
        with patch('builtins.print'):
            self.assertEqual(send_weekly_report(start, end, dry_run=True), 0)
        send.assert_not_called()
        save.assert_not_called()
        send_weekly_report(start, end)
        send.assert_called_once()
        blocks = send.call_args.args[0]
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[1]['elements'][0]['url'].endswith('/weekly/' + 'a' * 43))
        send.side_effect = RuntimeError('Slack unavailable')
        with self.assertRaises(RuntimeError):
            send_weekly_report(start, end)

    def test_html_escaping_grouping_and_incomplete_counts(self):
        start, end = weekly_window(week_ending='2026-10-22')
        reports = self.reports(2)
        reports[0]['country'] = '<script>alert(1)</script>'
        reports[0]['detail_loaded'] = 0
        reports[1]['submission_date'] = datetime(2026, 10, 16, 23, 30)
        html = build_weekly_html(reports, start, end)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertIn('data-date="2026-10-17"', html)
        self.assertIn('id="country-view" hidden', html)
        self.assertIn('미확인</span>', html)
        self.assertIn('추가 발생 2건', build_weekly_messages(reports, start, end)[0])

    def test_wahis_codes_and_report_number_fallback(self):
        self.assertEqual(report_kind({'report_type': 'IN'}), '최초 리포트')
        self.assertEqual(report_kind({'report_type': 'FUR'}), '후속 리포트')
        self.assertEqual(report_kind({'report_number': 0}), '최초 리포트')
        self.assertEqual(report_kind({'report_number': 1}), '후속 리포트')
        self.assertEqual(report_kind({}), '기타·미확인')


if __name__ == '__main__':
    unittest.main()
