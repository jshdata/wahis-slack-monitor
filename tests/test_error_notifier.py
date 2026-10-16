import json
import os
import unittest
from unittest.mock import Mock, patch

import main as monitor
from slack.error_notifier import ErrorReporter, redact


class ErrorNotificationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'SLACK_WEBHOOK_URL': 'https://example.test/webhook',
            'SLACK_ERROR_WEBHOOK_URL': '',
            'GITHUB_REPOSITORY': 'example/monitor', 'GITHUB_RUN_ID': '123',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.post = patch('slack.error_notifier.requests.post').start()
        self.addCleanup(patch.stopall)

    def test_secrets_and_slack_markup_are_redacted(self):
        with patch.dict(os.environ, {'DB_PASSWORD': 'test-db-secret', 'API_TOKEN': 'private-token'}):
            text = redact('test-db-secret private-token <@everyone> '
                          'https://hooks.slack.com/services/secret-path password=another-secret')
        self.assertNotIn('test-db-secret', text)
        self.assertNotIn('private-token', text)
        self.assertNotIn('another-secret', text)
        self.assertNotIn('secret-path', text)
        self.assertIn('&lt;@everyone&gt;', text)

    def test_duplicate_errors_group_and_flush_once(self):
        reporter = ErrorReporter('test')
        for report_id in range(5):
            reporter.record('DB', RuntimeError('disk full'), report_id=report_id)
        self.assertTrue(reporter.flush())
        self.post.assert_called_once()
        blocks = self.post.call_args.kwargs['json']['blocks']
        self.assertIn('*횟수:* 5', blocks[2]['text']['text'])
        self.assertEqual(blocks[-1]['elements'][0]['url'],
                         'https://github.com/example/monitor/actions/runs/123')
        self.assertTrue(all(len(b.get('text', {}).get('text', '')) <= 3000 for b in blocks))
        reporter.flush()
        self.post.assert_called_once()

    def test_no_errors_send_nothing_and_overflow_is_counted(self):
        reporter = ErrorReporter('test')
        reporter.run(lambda: None)
        self.post.assert_not_called()
        for number in range(20):
            reporter.record('DB', RuntimeError(str(number)))
        reporter.flush()
        payload = self.post.call_args.kwargs['json']
        self.assertIn('20건', payload['text'])
        self.assertIn('그 외 오류 12건', json.dumps(payload, ensure_ascii=False))

    def test_fatal_error_is_not_double_reported_and_still_raises(self):
        reporter = ErrorReporter('test')
        error = RuntimeError('API down')
        def work():
            reporter.call('API', Mock(side_effect=error), error_context={'page': 2})
        with self.assertRaises(RuntimeError) as raised:
            reporter.run(work)
        self.assertIs(raised.exception, error)
        self.assertIn('(1건)', self.post.call_args.kwargs['json']['text'])
        self.assertIn('page=2', json.dumps(self.post.call_args.kwargs['json']))

    def test_error_channel_and_send_failure_preserve_original_exception(self):
        reporter = ErrorReporter('test')
        self.post.side_effect = RuntimeError('webhook failed')
        with patch.dict(os.environ, {'SLACK_ERROR_WEBHOOK_URL': 'https://example.test/errors'}), \
                patch('builtins.print'):
            with self.assertRaisesRegex(ValueError, 'original'):
                reporter.run(Mock(side_effect=ValueError('original')))
        self.assertEqual(self.post.call_args.args[0], 'https://example.test/errors')
        self.post.assert_called_once()

    @patch('main.traceback.print_exc')
    @patch('main.time.sleep')
    @patch('builtins.print')
    def test_detail_retry_exhaustion_alerts_once_but_recovery_does_not(self, output, sleep, trace):
        reporter = ErrorReporter('test')
        with patch.object(monitor, 'ERRORS', reporter), \
                patch.object(monitor, 'get_report_detail', side_effect=RuntimeError('API down')):
            self.assertFalse(monitor.load_report_detail(7))
        self.assertEqual(reporter.total, 1)
        self.assertEqual(sleep.call_count, monitor.DETAIL_MAX_RETRIES - 1)
        reporter.flush()
        self.assertIn('report_id=7', json.dumps(self.post.call_args.kwargs['json']))
        reporter = ErrorReporter('test')
        with patch.object(monitor, 'ERRORS', reporter), \
                patch.object(monitor, 'get_report_detail', side_effect=[RuntimeError('transient'), {}]), \
                patch.object(monitor, 'save_report_detail'):
            self.assertTrue(monitor.load_report_detail(8))
        self.assertEqual(reporter.total, 0)

    @patch('main.traceback.print_exc')
    @patch('builtins.print')
    def test_slack_and_status_write_failures_are_both_recorded(self, output, trace):
        reporter = ErrorReporter('test')
        with patch.object(monitor, 'ERRORS', reporter), \
                patch.object(monitor, 'send_new_report_alert', side_effect=RuntimeError('Slack down')), \
                patch.object(monitor, 'mark_slack_failed', side_effect=RuntimeError('DB down')):
            self.assertFalse(monitor.send_and_record_slack({'reportId': 9}))
        self.assertEqual(reporter.total, 2)
        reporter.flush()
        self.post.assert_called_once()

    @patch('builtins.print')
    def test_fatal_collection_api_failure_has_page_and_no_real_db_calls(self, output):
        reporter = ErrorReporter('test')
        with patch.object(monitor, 'ERRORS', reporter), \
                patch.object(monitor, 'recover_unprocessed_details', return_value=(0, 0)), \
                patch.object(monitor, 'recover_unsent_slack_alerts', return_value=(0, 0)), \
                patch.object(monitor, 'get_events', side_effect=RuntimeError('API down')):
            with self.assertRaises(RuntimeError):
                reporter.run(monitor.main)
        payload = json.dumps(self.post.call_args.kwargs['json'], ensure_ascii=False)
        self.assertIn('WAHIS 목록 API 조회', payload)
        self.assertIn('page=1', payload)


if __name__ == '__main__':
    unittest.main()
