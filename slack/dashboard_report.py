"""Self-contained Plotly dashboard; filters run locally on an aggregated snapshot."""

import json
from pathlib import Path
from functools import lru_cache

from plotly import __version__ as PLOTLY_VERSION
from plotly.offline import get_plotlyjs
from slack.search_multi import MULTI_STYLE, MULTI_SCRIPT


PLOTLY_PATH = f'/assets/plotly-{PLOTLY_VERSION}.js'


@lru_cache(maxsize=1)
def plotly_script():
    return get_plotlyjs().encode('utf-8')


def build_dashboard_report(data, today, initial=None, inline_plotly=False):
    payload = json.dumps({'rows': data, 'today': today.isoformat(), 'initial': initial or {}},
                         ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    template = Path(__file__).with_name('dashboard_template.html').read_text(encoding='utf-8')
    library = ('<script>' + get_plotlyjs() + '</script>' if inline_plotly else
               f'<script src="{PLOTLY_PATH}"></script>')
    return (template.replace('<script>/*PLOTLY_LIBRARY*/</script>', library)
            .replace('/*MULTI_SELECT_STYLE*/', MULTI_STYLE)
            .replace('/*MULTI_SELECT_SCRIPT*/', MULTI_SCRIPT)
            .replace('/*DASHBOARD_DATA*/', payload))
