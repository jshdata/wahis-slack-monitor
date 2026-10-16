"""Year matrix for reported animal populations; never sum category totals and details."""
from html import escape

REGION_LABELS = {'Africa': '아프리카', 'Americas': '아메리카', 'Asia': '아시아',
                 'Europe': '유럽', 'Middle East': '중동', 'Oceania': '오세아니아',
                 'Unknown': '미분류'}
TYPE_LABELS = {'Terrestrial': '육상동물', 'Aquatic': '수생동물'}
METRICS = ('live_animals', 'animal_premises', 'total_meat_weight_tonnes')
FILTER_LABELS = {'region': '권역', 'country': '국가', 'animal_type': '동물 타입',
                 'animal_category': '동물 카테고리'}


def display_label(field, value):
    if field == 'region':
        return ' / '.join(REGION_LABELS.get(part, part) for part in value.split(' / '))
    return (REGION_LABELS if field == 'region' else TYPE_LABELS if field == 'animal_type' else {}).get(value, value)


def metric_label(metric, unit):
    if metric == 'animal_premises':
        return '사육시설·농장 수 (개)'
    if metric == 'total_meat_weight_tonnes':
        return '도축 고기 중량 (톤)'
    return {'Animals': '동물 수 (마리)', 'Hives / Nests': '벌통·둥지 수 (개)'}.get(unit, '동물 수 (단위 미보고)')


def population_matrix(data):
    years = sorted(data['years'])
    grouped = {}
    for row in data['rows']:
        key = (row['region'], row['country'], row['animal_type'], row['animal_category'],
               row['animal_subcategory'] or '', row['measuring_unit'] or '')
        values = grouped.setdefault(key, {})
        if row['year'] in values:
            raise ValueError('같은 국가·분류·연도에 보고서가 여러 개 있습니다. 원본 확인이 필요합니다.')
        values[row['year']] = row
    result = []
    for key, by_year in sorted(grouped.items()):
        for metric in METRICS:
            values = [by_year.get(year, {}).get(metric) for year in years]
            if any(value is not None for value in values):
                result.append((key, metric, values))
    return years, result


def format_number(value):
    if value is None:
        return '—'
    return format(value, ',.6f').rstrip('0').rstrip('.')


def build_population_report(data, today, filters=None):
    years, rows = population_matrix(data)
    filters = filters or {}
    labels = ' · '.join(f'{title}: ' + escape(', '.join(display_label(field, value)
                       for value in filters.get(field, [])) or '전체')
                       for field, title in FILTER_LABELS.items())
    head = ''.join(f'<th scope="col">{title}</th>' for title in
                   ('권역', '국가', '동물 타입', '동물 카테고리', '조회 항목', *years))
    body = []
    for key, metric, values in rows:
        region, country, animal_type, category, subcategory, unit = key
        category_html = escape(category) + (f'<small>{escape(subcategory)}</small>' if subcategory else '<small>카테고리 전체</small>')
        cells = ''.join(f'<td>{escape(value)}</td>' for value in
                        (display_label('region', region), country, display_label('animal_type', animal_type)))
        cells += f'<td>{category_html}</td><td>{escape(metric_label(metric, unit))}</td>'
        cells += ''.join(f'<td class="number {"missing" if value is None else "value"}">{format_number(value)}</td>'
                         for value in values)
        body.append(f'<tr data-region="{escape(region, quote=True)}" data-country="{escape(country, quote=True)}" '
                    f'data-type="{escape(animal_type, quote=True)}" data-category="{escape(category, quote=True)}" '
                    f'data-metric="{metric}">{cells}</tr>')
    options = {}
    for field, idx in (('region', 0), ('country', 1), ('animal_type', 2), ('animal_category', 3)):
        options[field] = sorted({key[idx] for key, _, _ in rows})
    options['region'] = sorted({part for key, _, _ in rows for part in key[0].split(' / ')})
    controls = []
    attrs = {'region': 'region', 'country': 'country', 'animal_type': 'type', 'animal_category': 'category'}
    for field, title in FILTER_LABELS.items():
        choices = ''.join(f'<option value="{escape(value, quote=True)}">{escape(display_label(field, value))}</option>'
                          for value in options[field])
        controls.append(f'<label>{title}<select data-field="{attrs[field]}"><option value="">전체</option>{choices}</select></label>')
    controls.append('<label>조회 항목<select data-field="metric"><option value="">전체</option>'
                    '<option value="live_animals">동물 수</option><option value="animal_premises">사육시설·농장 수</option>'
                    '<option value="total_meat_weight_tonnes">도축 고기 중량</option></select></label>')
    countries = len({key[1] for key, _, _ in rows})
    empty = f'<tr><td colspan="{5 + len(years)}">선택 조건에 해당하는 보고 수치가 없습니다.</td></tr>'
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>동물 개체수 조회</title>
<style>*{box-sizing:border-box}body{margin:0;padding:24px;background:#f4f6fa;color:#172033;font:14px system-ui,sans-serif}
h1{font-size:28px;margin:0 0 12px}.meta,.note{color:#526175;line-height:1.8}.filters{line-height:1.8}
.summary{margin:20px 0;display:flex;gap:28px;flex-wrap:wrap}.summary strong{font-size:23px;color:#183553}
.controls{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}label{display:grid;gap:6px;color:#526175}
select{padding:8px;border:1px solid #ccd4df;border-radius:6px;max-width:240px;background:white;color:#172033}
.scroll{overflow:auto;max-height:72vh;border:1px solid #ccd4df;border-radius:8px;background:white}
table{border-collapse:separate;border-spacing:0;font-variant-numeric:tabular-nums;min-width:100%}
th,td{padding:10px 14px;border-right:1px solid #e0e6ee;border-bottom:1px solid #e0e6ee;white-space:nowrap;text-align:left}
thead th{position:sticky;top:0;z-index:3;background:#183553;color:white;text-align:center;height:42px}
tbody tr:nth-child(even){background:#f7f9fc}tbody tr:hover{background:#e8f0fa}
small{display:block;white-space:normal;color:#617087;margin-top:4px;max-width:280px}
.number{text-align:right;min-width:125px}.value{color:#174d7c}.missing{color:#9aa6b5}
footer{margin-top:16px}tr[hidden]{display:none}@media(max-width:700px){body{padding:14px}.scroll{max-height:68vh}}
</style></head><body>''' + (
        f'<header><h1>동물 개체수 조회</h1><p class="meta">연도별 · 조회 기준: {today.isoformat()} (한국시간)</p>'
        f'<p class="filters">{labels}</p><p class="note">동물 타입: 육상동물(Terrestrial) / 수생동물(Aquatic). '
        '조회 항목별 단위는 표에 표시합니다.</p></header>'
        f'<div class="summary"><span><strong>{countries:,}</strong> 개 국가·지역</span>'
        f'<span><strong>{len(years)}</strong> 개 연도</span><span><strong id="row-count">{len(rows):,}</strong> 개 행</span></div>'
        f'<div class="controls">{"".join(controls)}</div><div class="scroll" tabindex="0" aria-label="연도별 동물 개체수 표">'
        f'<table><thead><tr>{head}</tr></thead><tbody id="data-rows">{"".join(body) or empty}</tbody></table></div>'
        '<p id="no-match" hidden>선택 조건에 해당하는 행이 없습니다.</p>'
        '<footer class="note">출처: WOAH WAHIS 연례보고서. 권역은 WAHIS 동물 개체수 대시보드 기준입니다.<br>'
        '—는 미보고 또는 자료 없음이며, 0은 보고된 0입니다. 모든 연도의 값이 없는 조회 항목은 표시하지 않습니다.<br>'
        '복수 권역에 속한 국가는 권역을 함께 표시합니다. 카테고리 전체와 세부 분류를 함께 표시하며 합계는 계산하지 않습니다. '
        '농장 수는 동물을 사육하는 시설 수이며, 벌은 마릿수 대신 벌통·둥지 수로 표시됩니다.</footer>'
        '''<script>const controls=[...document.querySelectorAll('select[data-field]')];
const rows=[...document.querySelectorAll('#data-rows tr[data-country]')];
function filterRows(){let count=0;for(const row of rows){row.hidden=!controls.every(select=>!select.value||(select.dataset.field==='region'?row.dataset.region.split(' / ').includes(select.value):row.dataset[select.dataset.field]===select.value));if(!row.hidden)count++;}
document.getElementById('row-count').textContent=count.toLocaleString('ko-KR');document.getElementById('no-match').hidden=count>0;}
controls.forEach(select=>select.addEventListener('change',filterRows));</script></body></html>''')
