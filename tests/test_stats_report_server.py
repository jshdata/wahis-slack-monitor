import os
import time
import unittest
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from slack.stats_report_server import create_report_server, report_url


class ReportServerTests(unittest.TestCase):
    def test_plotly_asset_is_served_with_immutable_cache(self):
        from slack.dashboard_report import PLOTLY_PATH
        server = create_report_server({}, host='127.0.0.1', port=0)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with urlopen(f'http://127.0.0.1:{server.server_port}{PLOTLY_PATH}', timeout=5) as response:
                self.assertIn(b'plotly', response.read()[:100].lower())
                self.assertIn('immutable', response.headers['Cache-Control'])
                self.assertIn('javascript', response.headers['Content-Type'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    @patch('slack.stats_report_server.load_weekly_html')
    def test_persistent_weekly_report_route(self, load):
        load.return_value = '<html>weekly</html>'
        server = create_report_server({}, host='127.0.0.1', port=0)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = f'http://127.0.0.1:{server.server_port}/weekly/' + 'a' * 43
        try:
            with urlopen(url, timeout=3) as response:
                self.assertEqual(response.read(), b'<html>weekly</html>')
            load.assert_called_with('a' * 43)
            load.return_value = None
            with self.assertRaises(HTTPError) as error:
                urlopen(url, timeout=3)
            self.assertEqual(error.exception.code, 404)
            load.side_effect = RuntimeError('DB unavailable')
            with self.assertRaises(HTTPError) as error:
                urlopen(url, timeout=3)
            self.assertEqual(error.exception.code, 503)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_public_url_configuration(self):
        with patch.dict(os.environ, {'RAILWAY_PUBLIC_DOMAIN': 'example.up.railway.app'}, clear=True):
            self.assertEqual(report_url('token'), 'https://example.up.railway.app/reports/token')
        with patch.dict(os.environ, {'STATS_REPORT_BASE_URL': 'https://example.test/'}, clear=True):
            self.assertEqual(report_url('token'), 'https://example.test/reports/token')
        with patch.dict(os.environ, {'RAILWAY_ENVIRONMENT_ID': 'production'}, clear=True):
            self.assertIsNone(report_url('token'))
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(report_url('token'), 'http://localhost:8765/reports/token')

    def test_reports_expiration_and_health(self):
        reports = {'valid': {'html': '<html>Matrix</html>', 'expires_at': time.time() + 60},
                   'dynamic': {'render': lambda params: 'page=' + params.get('page', ['0'])[0], 'expires_at': time.time() + 60},
                   'expired': {'html': 'expired', 'expires_at': time.time() - 1}}
        server = create_report_server(reports, host='127.0.0.1', port=0)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/reports/valid', timeout=3) as response:
                self.assertEqual(response.read(), b'<html>Matrix</html>')
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
            with urlopen(base + '/health', timeout=3) as response:
                self.assertEqual(response.read(), b'ok')
            with urlopen(base + '/reports/dynamic?page=3', timeout=3) as response:
                self.assertEqual(response.read(), b'page=3')
            for path in ('/reports/expired', '/reports/missing', '/reports/../valid'):
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + path, timeout=3)
                self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
