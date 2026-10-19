"""Serve short-lived Matrix reports without sending Slack messages."""

import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit, parse_qs
import logging

from database.weekly_report_db import load_weekly_html

REPORT_TTL_SECONDS = 3600


def report_base_url():
    configured = os.getenv('STATS_REPORT_BASE_URL', '').strip().rstrip('/')
    if configured:
        return configured
    domain = os.getenv('RAILWAY_PUBLIC_DOMAIN', '').strip()
    if domain:
        return f'https://{domain}'
    if os.getenv('RAILWAY_ENVIRONMENT_ID'):
        return None
    return f'http://localhost:{os.getenv("PORT", "8765")}'


def report_url(key):
    base = report_base_url()
    return f'{base}/reports/{key}' if base else None


def create_report_server(reports, host='0.0.0.0', port=8765):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/health':
                content, status = b'ok', 200
                content_type = 'text/plain; charset=utf-8'
            elif path.startswith('/assets/plotly-'):
                from slack.dashboard_report import PLOTLY_PATH, plotly_script
                content, status = (plotly_script(), 200) if path == PLOTLY_PATH else (b'Not found', 404)
                content_type = 'application/javascript; charset=utf-8'
            elif path.startswith('/weekly/'):
                try:
                    html = load_weekly_html(path.removeprefix('/weekly/'))
                    status = 200 if html else 404
                    content = (html or '주간 리포트가 만료되었거나 존재하지 않습니다.').encode('utf-8')
                except Exception:
                    status = 503
                    content = '리포트를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.'.encode('utf-8')
                content_type = 'text/html; charset=utf-8'
            else:
                key = path.removeprefix('/reports/') if path.startswith('/reports/') else ''
                report = reports.get(key)
                if report and time.time() < report['expires_at']:
                    try:
                        html = report['render'](parse_qs(urlsplit(self.path).query)) if 'render' in report else report['html']
                        content, status = html.encode('utf-8'), 200
                    except Exception as error:
                        logging.getLogger(__name__).warning('HTML report rendering failed: %s', type(error).__name__)
                        content, status = '표를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.'.encode('utf-8'), 503
                else:
                    content = '표 링크가 만료되었거나 존재하지 않습니다. Slack에서 다시 조회해주세요.'.encode('utf-8')
                    status = 404
                content_type = 'text/html; charset=utf-8'
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'public, max-age=31536000, immutable'
                             if content_type.startswith('application/javascript') and status == 200
                             else 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format, *args):
            # Report URLs contain bearer tokens; do not write them to logs.
            pass

    return ThreadingHTTPServer((host, port), Handler)


def start_report_server(reports):
    server = create_report_server(reports, port=int(os.getenv('PORT', '8765')))
    Thread(target=server.serve_forever, name='stats-reports', daemon=True).start()
    return server
