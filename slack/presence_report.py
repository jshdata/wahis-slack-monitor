"""Occurrence O/blank HTML tables with merged regions and year headings."""

from collections import defaultdict
from html import escape

LABELS = {
    'HPAI': 'HPAI - 가금 (Poultry)',
    'HPAI_NON_POULTRY': 'HPAI - 가금 외 (Non-poultry)',
    'ASF': 'ASF - 아프리카돼지열병', 'FMD': 'FMD - 구제역',
    'LSD': 'LSD - 럼피스킨병', 'BSE': 'BSE - 소해면상뇌증',
}
REGIONS = [('Asia', '아시아'), ('Europe', '유럽'), ('Africa', '아프리카'),
           ('America', '아메리카'), ('Oceania', '오세아니아'), ('Other', '기타')]


def region_key(region):
    if region in ('North America', 'South America'):
        return 'America'
    return region if region in dict(REGIONS) else 'Other'


def table_model(countries, facts, unit, today):
    # Ignore future dates when constructing an observation table through today.
    facts = {(c, y, m) for c, y, m in facts if (y, m) <= (today.year, today.month)}
    first_year = min((y for _, y, _ in facts), default=today.year)
    periods = ([(y,) for y in range(first_year, today.year + 1)] if unit == 'year' else
               [(y, m) for y in range(first_year, today.year + 1)
                for m in range(1, 13) if (y, m) <= (today.year, today.month)])
    hits = {(c, y) if unit == 'year' else (c, y, m) for c, y, m in facts}
    mapping = {country: region_key(region) for country, region in countries}
    for country, _, _ in facts:
        mapping.setdefault(country, 'Other')
    groups = defaultdict(list)
    totals = [0] * len(periods)
    for country in sorted(mapping):
        values = [int((country, *period) in hits) for period in periods]
        for index, value in enumerate(values):
            totals[index] += value
        groups[mapping[country]].append((country, values))
    return periods, groups, totals


def render_table(countries, facts, unit, today):
    periods, groups, totals = table_model(countries, facts, unit, today)
    rows = []
    for region, label in REGIONS:
        members = groups[region]
        for index, (country, values) in enumerate(members):
            cells = (f'<th class="region" scope="rowgroup" rowspan="{len(members)}"><span class="region-label">{label}</span></th>'
                     if index == 0 else '')
            cells += f'<th class="country" scope="row">{escape(country)}</th>'
            cells += ''.join('<td class="yes">O</td>' if v else '<td></td>' for v in values)
            cells += f'<td class="row-total">{sum(values)}</td>'
            rows.append(f'<tr>{cells}</tr>')
    if unit == 'year':
        head = '<tr><th class="region">권역</th><th class="country">국가</th>'
        head += ''.join(f'<th>{y}</th>' for (y,) in periods) + '<th>O 합계</th></tr>'
    else:
        by_year = defaultdict(int)
        for year, _ in periods:
            by_year[year] += 1
        head = '<tr><th class="region" rowspan="2">권역</th><th class="country" rowspan="2">국가</th>'
        head += ''.join(f'<th colspan="{count}">{year}년</th>' for year, count in by_year.items())
        head += '<th rowspan="2">O 합계</th></tr><tr>'
        head += ''.join(f'<th>{month}월</th>' for _, month in periods) + '</tr>'
    footer = '<tr><th colspan="2">날짜별 O 합계</th>'
    footer += ''.join(f'<td>{n}</td>' for n in totals) + f'<td class="grand-total">{sum(totals)}</td></tr>'
    label = '연도별' if unit == 'year' else '월별'
    return (f'<h3>{label} · 총 O 합계: {sum(totals):,}</h3>'
            f'<div class="scroll"><table class="{unit}"><thead>{head}</thead>'
            f'<tbody>{"".join(rows)}</tbody><tfoot>{footer}</tfoot></table></div>')


def build_presence_report(countries, facts_by_disease, mode, today):
    if mode not in ('year', 'month', 'both'):
        raise ValueError('지원하지 않는 표시 단위입니다.')
    units = ('year', 'month') if mode == 'both' else (mode,)
    sections = []
    for code, facts in facts_by_disease.items():
        content = f'<section><h2>{escape(LABELS[code])}</h2>'
        if not facts:
            content += '<p>저장된 발생일이 없습니다. 모든 국가를 공백으로 표시합니다.</p>'
        content += ''.join(render_table(countries, facts, unit, today) for unit in units)
        sections.append(content + '</section>')
    return '''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>질병별 발생 여부</title><style>
*{box-sizing:border-box}body{margin:0;padding:24px;font:14px system-ui,sans-serif;background:#f4f6fa;color:#172033}
.scroll{overflow:auto;max-height:76vh;border:1px solid #ccd4df;margin-bottom:32px}
table{border-collapse:separate;border-spacing:0;background:white;font-variant-numeric:tabular-nums}
th,td{min-width:64px;padding:10px;border-right:1px solid #dbe1e9;border-bottom:1px solid #dbe1e9;text-align:center;white-space:nowrap}
thead th{position:sticky;top:0;background:#183553;color:white;z-index:3;height:42px}
table.month thead tr:nth-child(2) th{top:42px}thead th[rowspan]{vertical-align:middle}
.region{min-width:100px;width:100px;position:sticky;left:0;background:#e6edf7;color:#172033;z-index:2}
.country{min-width:240px;position:sticky;left:100px;text-align:left;background:#f3f6fa;z-index:2}
thead .region,thead .country{z-index:5;background:#183553;color:white}
tbody th.region{vertical-align:top;padding-top:18px}
.region-label{display:block;position:sticky;top:54px}.month .region-label{top:96px}
.yes{color:#174b30;background:#e9f5ee;font-weight:700}
.row-total{position:sticky;right:0;z-index:2;font-weight:700;background:#edf3fb}
thead tr:first-child th:last-child{right:0;z-index:6}
tfoot th,tfoot td{position:sticky;bottom:0;z-index:4;background:#dce9f7;font-weight:700}
tfoot th{left:0;text-align:left;z-index:6}.grand-total{right:0;z-index:7;background:#b9d5f4}
section{margin-bottom:40px}h2{margin:24px 0 12px}p{line-height:1.6}
</style><h1>질병별 발생 여부</h1>
<p>전체 기간 · 발생일(outbreak.start_date) 기준 · O: 해당 국가·기간에 1건 이상 발생 기록 · 공백: 발생 기록 없음<br>
O는 발생 건수가 아니라 발생한 국가·기간 조합의 수입니다. 연도별 O와 월별 O는 각각 계산하며 서로 더하지 않습니다.</p>
''' + f'<p>조회 기준: {today.isoformat()} (한국시간) · DB에 등록된 모든 국가 포함</p>' + ''.join(sections) + '</html>'
