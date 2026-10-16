"""Standalone weekly digest with date/country views and local filtering."""

from collections import defaultdict
from datetime import timedelta, timezone
from html import escape

from slack.notifier import get_reason_label
from slack.weekly_report import KST, outbreak_count, report_kind, report_value, summary
from slack.search_multi import MULTI_STYLE, MULTI_SCRIPT


def local_date(report):
    return report['submission_date'].replace(tzinfo=timezone.utc).astimezone(KST)


def stats_text(reports):
    counts = summary(reports)
    text = (f'리포트 {counts["reports"]:,}건 · 후속 {counts["followups"]:,}건 · '
            f'추가 발생 {counts["outbreaks"]:,}건')
    if counts['incomplete']:
        text += f' · 상세 미수집 {counts["incomplete"]}건'
    return text


def report_row(report):
    url = (f'https://wahis.woah.org/#/in-review/{int(report["event_id"])}'
           f'?reportId={int(report["report_id"])}&fromPage=event-dashboard-url')
    count = outbreak_count(report)
    number = report.get('report_number')
    report_type = report_value(report, 'report_type', 'reportType')
    if number is not None:
        report_type = f'보고 차수 {int(number)}'
    elif report_type.upper() in ('IN', 'FUR'):
        report_type = report_kind(report)
    cells = [
        f'<time>{local_date(report):%m-%d %H:%M}</time>',
        escape(report['disease']),
        f'<span class="badge">{escape(report_kind(report))}</span>'
        f'<small>{escape(report_type)}</small>',
        f'<strong>{count:,}</strong>' if count is not None else '<span class="muted">미확인</span>',
        escape(report.get('subtype') or '미확인'),
        escape(get_reason_label(report_value(report, 'reason', 'reason'))),
        escape(report_value(report, 'event_status', 'eventStatus')),
        f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
        f'Report {int(report["report_id"])} ↗</a>'
        f'<small>Event {int(report["event_id"])}</small>',
    ]
    return '<tr>' + ''.join(f'<td>{cell}</td>' for cell in cells) + '</tr>'


def render_group(items, country, date, disease):
    rows = ''.join(report_row(r) for r in sorted(items, key=local_date))
    return (
        f'<details open class="group" data-country="{escape(country, quote=True)}" '
        f'data-date="{date}" data-disease="{escape(disease, quote=True)}">'
        f'<summary>{escape(country)} <span>{date} · {escape(disease)}</span>'
        f'<small>{stats_text(items)}</small></summary><div class="scroll"><table>'
        '<thead><tr><th>제출 (KST)</th><th>질병</th><th>보고 구분</th><th>추가 발생</th>'
        '<th>아형</th><th>발생 사유</th><th>이벤트 상태</th><th>원문 리포트</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></div></details>'
    )


def build_weekly_html(reports, start, end):
    counts = summary(reports)
    by_date = defaultdict(lambda: defaultdict(list))
    by_country = defaultdict(lambda: defaultdict(list))
    by_disease = defaultdict(lambda: defaultdict(list))
    for report in reports:
        date = local_date(report).strftime('%Y-%m-%d')
        country, disease = report['country'], report['disease']
        by_date[date][(country, disease)].append(report)
        by_country[country][(date, disease)].append(report)
        by_disease[disease][(country, date)].append(report)
    panels = []
    for name, groups in [('date', by_date), ('country', by_country), ('disease', by_disease)]:
        sections = []
        for key in sorted(groups, reverse=name == 'date'):
            all_items = [r for items in groups[key].values() for r in items]
            details = []
            for subkey, items in sorted(groups[key].items(), reverse=name == 'country'):
                if name == 'date':
                    country, disease = subkey
                    date = key
                elif name == 'country':
                    date, disease = subkey
                    country = key
                else:
                    country, date = subkey
                    disease = key
                details.append(render_group(items, country, date, disease))
            sections.append(f'<section class="section"><h2>{escape(key)}</h2>'
                            f'<p class="muted">{stats_text(all_items)}</p>{"".join(details)}</section>')
        hidden = ' hidden' if name != 'date' else ''
        panels.append(f'<div id="{name}-view"{hidden}>' + ''.join(sections) + '</div>')
    countries = ''.join(f'<option>{escape(country)}</option>' for country in sorted(by_country))
    dates = ''.join(f'<option>{date}</option>' for date in sorted(by_date, reverse=True))
    diseases = ''.join(f'<option>{escape(disease)}</option>' for disease in sorted(by_disease))
    cards = ''.join(f'<div class="card"><span>{label}</span><strong>{value:,}<small>{unit}</small>'
                    '</strong></div>' for label, value, unit in [
                        ('전체 리포트', counts['reports'], '건'), ('보고 국가', counts['countries'], '개'),
                        ('보고 질병', counts['diseases'], '개'), ('후속 리포트', counts['followups'], '건'),
                        ('추가 발생', counts['outbreaks'], '건')])
    empty = '<p class="empty">해당 기간에 제출된 신규 리포트가 없습니다.</p>' if not reports else ''
    html = '''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WAHIS 주간 리포트</title><style>
:root{color-scheme:light;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#1c3047;background:#f3f6fa}
*{box-sizing:border-box}body{margin:0}main{max-width:1500px;margin:auto;padding:36px 28px 70px}
header{display:flex;justify-content:space-between;align-items:center;gap:20px}.eyebrow{font-size:12px;letter-spacing:2px;color:#527086;font-weight:700}
h1{font-size:32px;margin:12px 0}h2{font-size:23px;margin:0}.muted,small{color:#617387}small{display:block;font-size:12px;margin-top:7px}
.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin:28px 0}.card{background:white;padding:22px;border:1px solid #dfe7ee;border-radius:14px}
.card span{font-size:13px;color:#617387}.card strong{display:block;font-size:32px;margin-top:12px}.card strong small{display:inline;margin-left:6px}
.note{font-size:13px;line-height:1.8;background:#e9f1f7;padding:18px 22px;border-radius:12px}.toolbar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;background:#f3f6fa;padding:18px 0;position:sticky;top:0;z-index:2}
button,select{font:inherit;border:1px solid #cbd7e2;border-radius:8px;background:white;padding:10px 14px;cursor:pointer}button[aria-pressed=true]{background:#1c405e;color:white;border-color:#1c405e}
.section{margin:28px 0}.group{background:white;border:1px solid #dfe7ee;border-radius:12px;margin:12px 0;overflow:hidden}summary{padding:18px 20px;cursor:pointer;font-weight:650}summary span{margin-left:14px;color:#617387;font-weight:400}.scroll{overflow:auto}
table{width:100%;border-collapse:collapse;min-width:1050px;font-size:13px}th,td{padding:15px 16px;text-align:left;border-top:1px solid #e6edf3;vertical-align:top;line-height:1.6}th{background:#f8fafc;font-size:12px;color:#617387}td:nth-child(4){text-align:right}a{color:#146c9f;text-decoration:none;white-space:nowrap}a:hover{text-decoration:underline}.badge{display:inline-block;border-radius:5px;background:#edf3f7;padding:2px 6px;white-space:nowrap}.empty{padding:35px;text-align:center}
[hidden]{display:none!important}@media(max-width:800px){main{padding:22px 14px}h1{font-size:26px}.cards{grid-template-columns:repeat(2,1fr)}.card:last-child{grid-column:span 2}.toolbar{position:static}header{align-items:flex-start}}
@media print{.toolbar,header button{display:none}body{background:white}.scroll{overflow:visible}table{min-width:0}.group{break-inside:avoid}main{padding:0}.card{padding:10px}}
</style><style>/*MULTI_STYLE*/</style></head><body><main><header><div><div class="eyebrow">WAHIS / WEEKLY DIGEST</div>
<h1>한 주의 동물질병 리포트</h1>''' + (
        f'<p class="muted">{start:%Y.%m.%d %H:%M} — '
        f'{end - timedelta(seconds=1):%Y.%m.%d %H:%M} · 서울시간</p></div>'
        '<button onclick="window.print()">인쇄 / PDF 저장</button></header>'
        f'<div class="cards">{cards}</div>'
        '<div class="note">WAHIS 제출시각 기준으로 최초 보고와 후속 보고를 함께 정리했습니다. '
        '<b>후속 리포트</b>는 기존 이벤트에 대한 추가 보고이며, '
        '<b>추가 발생</b>은 이 기간의 리포트에서 처음 등록된 고유 outbreak 수입니다. '
        '기존 outbreak의 수정은 추가 발생에 포함하지 않습니다. '
        f'상세 미수집 리포트 {counts["incomplete"]}건은 발생건수 합계에서 제외하고 미확인으로 표시합니다. '
        '신규 공개·수집이 늦어진 리포트는 조회 시점에 따라 달라질 수 있습니다.</div>'
        '<div class="toolbar"><div role="group" aria-label="묶음 기준">'
        '<button id="date-button" aria-pressed="true" onclick="setView(\'date\')">날짜별</button> '
        '<button id="country-button" aria-pressed="false" onclick="setView(\'country\')">국가별</button> '
        '<button id="disease-button" aria-pressed="false" onclick="setView(\'disease\')">질병별</button></div>'
        f'<label>국가 <select id="country-filter"><option value="">전체 국가</option>{countries}</select></label>'
        f'<label>날짜 <select id="date-filter"><option value="">전체 날짜</option>{dates}</select></label>'
        f'<label>질병 <select id="disease-filter"><option value="">전체 질병</option>{diseases}</select></label>'
        '<button onclick="setOpen(false)">모두 접기</button><button onclick="setOpen(true)">모두 펼치기</button>'
        '<small>상단 합계는 전체 조회기간 기준입니다.</small></div>'
        f'{empty}<p id="no-match" class="empty" hidden>선택한 조건에 해당하는 리포트가 없습니다.</p>'
        + ''.join(panels)
    ) + '''</main><script>
/*MULTI_SCRIPT*/
let view='date';
function setView(next){view=next;for(const name of ['date','country','disease']){document.getElementById(name+'-view').hidden=name!==view;document.getElementById(name+'-button').setAttribute('aria-pressed',String(name===view))}filterGroups()}
function filterGroups(){const countries=multiValues('country-filter'),dates=multiValues('date-filter'),diseases=multiValues('disease-filter');let matches=0;document.querySelectorAll('.group').forEach(group=>{group.hidden=Boolean((countries.length&&!countries.includes(group.dataset.country))||(dates.length&&!dates.includes(group.dataset.date))||(diseases.length&&!diseases.includes(group.dataset.disease)))});document.querySelectorAll('.section').forEach(section=>{section.hidden=![...section.querySelectorAll('.group')].some(group=>!group.hidden)});document.querySelectorAll('#'+view+'-view .group').forEach(group=>{if(!group.hidden)matches++});document.getElementById('no-match').hidden=Boolean(matches)||(!countries.length&&!dates.length&&!diseases.length)}
function setOpen(open){document.querySelectorAll('#'+view+'-view .group').forEach(group=>group.open=open)}
document.getElementById('country-filter').addEventListener('change',filterGroups);
document.getElementById('date-filter').addEventListener('change',filterGroups);
document.getElementById('disease-filter').addEventListener('change',filterGroups);
for(const id of ['country-filter','date-filter','disease-filter']){const select=document.getElementById(id);new SearchMultiSelect(select,select.options[0].text)}
</script></body></html>'''
    return html.replace('/*MULTI_STYLE*/', MULTI_STYLE).replace('/*MULTI_SCRIPT*/', MULTI_SCRIPT)
