"""Year/month import count matrix with fixed label columns and source coverage."""
from collections import defaultdict
from html import escape

from database.import_counts_db import month_range


def import_count_matrix(data, mode):
    if mode not in ("year", "month"):
        raise ValueError("연도별 또는 월별을 선택해주세요.")
    latest = data["latest_month"]
    periods = (list(range(2020, latest.year + 1)) if mode == "year" else
               [month.strftime("%Y-%m") for month in month_range(latest)])
    positions = {period: i for i, period in enumerate(periods)}
    groups = defaultdict(lambda: [0] * len(periods))
    for category, product, country, month, count in data["rows"]:
        period = month.year if mode == "year" else month.strftime("%Y-%m")
        if period in positions:
            groups[category, product, country][positions[period]] += count
    rows = [(key, values) for key, values in sorted(groups.items()) if any(values)]
    totals = [sum(values[i] for _, values in rows) for i in range(len(periods))]
    return periods, rows, totals


def build_import_counts_report(data, mode, today, filters=None):
    periods, rows, totals = import_count_matrix(data, mode)
    latest = data["latest_month"]
    mode_label = "연도별" if mode == "year" else "월별"
    filters = filters or {}
    labels = " · ".join(f"{title}: " + escape(", ".join(v or "(공백)" for v in filters.get(key, [])) or "전체")
                        for key, title in (("category", "품목"), ("product", "품명"), ("country", "국가")))
    fixed = ''.join(f'<th class="key k{i}" scope="col"' + (' rowspan="2"' if mode == 'month' else '') +
                    f'>{label}</th>' for i, label in enumerate(('품목', '품명', '국가')))
    if mode == "year":
        head = '<tr>' + fixed + ''.join(f'<th scope="col">{y}년</th>' for y in periods) + '</tr>'
    else:
        years = defaultdict(int)
        for period in periods:
            years[period[:4]] += 1
        head = '<tr>' + fixed + ''.join(f'<th colspan="{n}" scope="colgroup">{y}년</th>'
                                       for y, n in years.items()) + '</tr><tr>'
        head += ''.join(f'<th scope="col">{int(p[5:])}월</th>' for p in periods) + '</tr>'
    body = []
    for key, values in rows:
        cells = ''.join(f'<td class="key k{i}">{escape(value)}</td>' for i, value in enumerate(key))
        cells += ''.join(f'<td class="{"positive" if n else "zero"}">{n:,}</td>' for n in values)
        body.append('<tr>' + cells + '</tr>')
    if not rows:
        body.append(f'<tr><td class="empty" colspan="{len(periods) + 3}">선택 조건에 해당하는 수입건수가 없습니다.</td></tr>')
    footer = '<tr><th colspan="3">기간별 합계</th>' + ''.join(f'<td>{n:,}</td>' for n in totals) + '</tr>'
    partial = (f' · {latest.year}년은 1~{latest.month}월 자료' if latest.month != 12 else '')
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>수입건수</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f4f6fa;color:#172033;font:14px system-ui,sans-serif;padding:24px}
header{max-width:1100px}h1{font-size:28px;margin:0 0 12px}.meta{line-height:1.8;color:#526175}.filters{line-height:1.7}
.summary{display:flex;gap:28px;flex-wrap:wrap;margin:22px 0}.summary span{color:#526175}.summary strong{font-size:23px;color:#183553;margin-right:6px}
.scroll{overflow:auto;max-height:74vh;border:1px solid #ccd4df;border-radius:8px;background:white}
table{border-collapse:separate;border-spacing:0;font-variant-numeric:tabular-nums}
th,td{min-width:86px;padding:10px 14px;border-right:1px solid #e0e6ee;border-bottom:1px solid #e0e6ee;white-space:nowrap;text-align:right}
thead th{position:sticky;top:0;z-index:3;background:#183553;color:#fff;text-align:center;height:42px}
.month thead tr:nth-child(2) th{top:42px}.key{position:sticky;z-index:2;background:#fff;text-align:left}
.k0{left:0;min-width:126px;max-width:126px;width:126px;overflow:hidden;text-overflow:ellipsis}
.k1{left:126px;min-width:206px;max-width:206px;width:206px;overflow:hidden;text-overflow:ellipsis}
.k2{left:332px;min-width:160px;max-width:160px;width:160px;overflow:hidden;text-overflow:ellipsis;border-right:2px solid #bccbde}
thead .key{z-index:5;background:#183553}tbody tr:nth-child(even) .key{background:#f7f9fc}
.positive{color:#174d7c;background:#edf5ff}.zero{color:#9aa6b5}tbody tr:hover td{background:#e8f0fa}
tfoot th,tfoot td{position:sticky;bottom:0;z-index:4;background:#dce9f7;font-weight:700}tfoot th{left:0;text-align:left;z-index:6}
.empty{padding:28px;text-align:left;color:#526175}footer{color:#617087;line-height:1.7;margin-top:16px}
@media(max-width:700px){body{padding:14px}.scroll{max-height:70vh}}
</style></head><body><header><h1>수입건수</h1>''' + (
        f'<p class="meta">{mode_label} · 2020년 1월~{latest.year}년 {latest.month}월{partial}<br>'
        f'조회 기준: {today.isoformat()} (한국시간)</p><p class="filters">{labels}</p></header>'
        f'<div class="summary"><div><strong>{sum(totals):,}</strong><span>건</span></div>'
        f'<div><strong>{len(rows):,}</strong><span>개 행</span></div>'
        f'<div><strong>{len(periods)}</strong><span>개 기간</span></div></div>'
        f'<div class="scroll" tabindex="0" aria-label="{mode_label} 수입건수 표"><table class="{mode}">'
        f'<thead>{head}</thead><tbody>{"".join(body)}</tbody><tfoot>{footer}</tfoot></table></div>'
        '<footer>농림축산검역본부 수출입현황(No2)의 수입동물·수입축산물 건수입니다. '
        '전체 기간에 건수가 없는 행은 표시하지 않습니다.<br>'
        '빈 이름은 원본대로 공백으로 표시하며, 같은 품목·품명·국가의 별도 원본 행은 건수를 합산합니다. '
        '당해 연도 자료는 잠정치로 수정될 수 있습니다.</footer></body></html>')
