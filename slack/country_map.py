"""Exact country matching for a bundled, public-domain reference boundary."""
import json
from functools import lru_cache
from pathlib import Path
import unicodedata


def normalized_name(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())


ALIASES = {
    'united states': 'United States of America',
    'united kingdom': 'United Kingdom',
    'korea (rep. of)': 'South Korea',
    'korea (dem. people\'s rep.)': 'North Korea',
    'russian federation': 'Russia',
    'iran (islamic rep. of)': 'Iran',
    'tanzania (united rep. of)': 'United Republic of Tanzania',
    'viet nam': 'Vietnam',
    'lao (people\'s dem. rep.)': 'Laos',
    'china (people\'s rep. of)': 'China',
    'hong kong (sar - prc)': 'Hong Kong S.A.R.',
}


@lru_cache(maxsize=1)
def boundary_index():
    data = json.loads((Path(__file__).resolve().parents[1] /
                       'config/country_boundaries.geojson').read_text(encoding='utf-8'))
    index = {}
    for feature in data['features']:
        for key in ('ADMIN', 'NAME', 'NAME_LONG', 'FORMAL_EN', 'BRK_NAME'):
            name = normalized_name(feature['properties'].get(key))
            if name:
                index.setdefault(name, []).append(feature)
    return index


def country_boundary(country):
    name = normalized_name(country)
    name = normalized_name(ALIASES.get(name, country))
    # Unknown names must not shade a nearby or similarly named country.
    features, seen = [], set()
    for feature in boundary_index().get(name, []):
        identifier = feature['properties']['ADMIN']
        if identifier not in seen:
            features.append(feature)
            seen.add(identifier)
    return {'type': 'FeatureCollection', 'features': features}
