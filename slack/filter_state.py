"""Keep large multi-country filters within Slack button/metadata size limits."""

import json
import time
from threading import Lock
from uuid import uuid4

_FILTERS = {}
_LOCK = Lock()


def encode_filters(params):
    raw = json.dumps(params, ensure_ascii=False)
    if len(raw) <= 1800:
        return raw
    token = uuid4().hex
    now = time.time()
    with _LOCK:
        for key in list(_FILTERS):
            if _FILTERS[key][0] <= now:
                _FILTERS.pop(key, None)
        _FILTERS[token] = (now + 3600, raw)
        while len(_FILTERS) > 500:
            _FILTERS.pop(next(iter(_FILTERS)))
    return json.dumps({'_filter_token': token})


def decode_filters(raw):
    params = json.loads(raw)
    if '_filter_token' not in params:
        return params
    with _LOCK:
        entry = _FILTERS.get(params['_filter_token'])
        if not entry or entry[0] <= time.time():
            raise ValueError('조회 조건이 만료되었습니다. 통계를 다시 조회해주세요.')
        return json.loads(entry[1])
