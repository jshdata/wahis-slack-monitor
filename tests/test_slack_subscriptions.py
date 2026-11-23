import os
import unittest
from unittest.mock import MagicMock, patch

from slack import subscriptions


class SlackSubscriptionsTests(unittest.TestCase):
    def test_exact_match_uses_or_within_and_across_fields(self):
        env = {
            'WAHIS_SLACK_SUBSCRIPTIONS': '[{"name":"poultry","webhook_env":"POULTRY_URL",'
                                        '"countries":["France","Germany"],"species":[" Chicken "]}]',
            'POULTRY_URL': 'https://hooks.slack.com/services/T/B/example',
        }
        with patch.dict(os.environ, env, clear=True):
            rule, = subscriptions.get_subscriptions()
        event = {'country': 'GERMANY'}
        self.assertTrue(subscriptions.matches(rule, event, {'species_names': ['chicken']}))
        self.assertFalse(subscriptions.matches(rule, event, {'species_names': ['Wild chicken']}))
        self.assertFalse(subscriptions.matches(rule, event, {'species': 'Chicken (사육)'}))
        self.assertFalse(subscriptions.matches(rule, {'country': 'Spain'}, {'species_names': ['Chicken']}))

    @patch.object(subscriptions, 'get_connection')
    def test_retry_skips_default_after_subscription_failure(self, connect):
        conn = connect.return_value
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [(1,), None, None, (1,), (1,), None]
        send = MagicMock(side_effect=[None, RuntimeError('offline'), None])
        rules = [{'countries': {'france'}, 'diseases': set(), 'species': set(),
                  'name': 'france', 'url': 'webhook'}]
        args = ({'reportId': 123, 'country': 'France'}, {}, rules, [], 'report', send)
        with self.assertRaisesRegex(RuntimeError, 'destinations: france'):
            subscriptions.send_subscribed_alert(*args)
        subscriptions.send_subscribed_alert(*args)
        self.assertEqual([call.kwargs['webhook_url'] for call in send.call_args_list],
                         [None, 'webhook', 'webhook'])
        self.assertEqual(conn.commit.call_count, 2)
