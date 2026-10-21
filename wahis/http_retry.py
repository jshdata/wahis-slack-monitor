"""Parse server retry delays without importing a CLI entry point."""
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def retry_after_seconds(response):
    value = response.headers.get('Retry-After', '') if response is not None else ''
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 0
    return max(0, seconds) if math.isfinite(seconds) else 0
