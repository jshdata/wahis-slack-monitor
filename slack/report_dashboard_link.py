"""Optional report-specific URL; never change existing notification delivery."""
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def report_dashboard_url(report_id):
    base = os.getenv('STREAMLIT_DASHBOARD_URL', '').strip()
    parts = urlsplit(base)
    if parts.scheme != 'https' or not parts.netloc or parts.username or parts.password:
        return None
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != 'report_id']
    query.append(('report_id', str(int(report_id))))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
