import os
import time
import unittest
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from slack.stats_report_server import create_report_server, report_url


class ReportServerTests(unittest.TestCase):
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
