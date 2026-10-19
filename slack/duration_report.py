"""Copyable annual outbreak counts and estimated observation-day tables."""
from datetime import date
from html import escape


def build_duration_report(items):
    def e(value):
        return escape(str(value if value is not None else ''))
    headers = ['연도', '질병·구분', '권역', '국가', '발생건수', '관찰구간 수',
               '추정 관찰기간(일)', '비율(%)', '조회 시작일', '조회 종료일', '조회 일수', '관찰 기준(일)']
    rows, summaries = [], []
    for item in items:
        start, end = item['start_date'], item['end_date']
        period_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
        if period_days <= 0:
            raise ValueError('Invalid duration report period')
        summaries.append(f"{item['year']} · {item['disease']} · {item['region_label']} · {item['country_label']} · {start} ~ {end}")
        for country, region, outbreaks, episodes, days in item['rows']:
            days = int(days)
            rows.append([item['year'], item['disease'], region, country, int(outbreaks), int(episodes),
                         days, f'{days / period_days * 100:.1f}', start, end, period_days, item['gap_days']])
    body = ''.join('<tr>' + ''.join(f'<td>{e(cell)}</td>' for cell in row) + '</tr>' for row in rows)
    if not rows:
        body = '<tr data-empty="true"><td colspan="12">조회 결과가 없습니다.</td></tr>'
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">
<title>WAHIS 연도별 발생건수·추정 관찰기간</title><style>
*{box-sizing:border-box}body{margin:0;padding:24px;background:#f4f6fa;color:#172033;font:15px system-ui,sans-serif}
h1{font-size:25px}p,summary,details{line-height:1.7}.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:18px 0}
button,input{padding:10px 14px;font:inherit;border:1px solid #bfcddd;border-radius:7px;background:white}button{cursor:pointer}
.scroll{overflow:auto;max-height:75vh;border:1px solid #ccd4df;background:white}
table{border-collapse:separate;border-spacing:0;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:10px 12px;border-bottom:1px solid #dbe1e9;border-right:1px solid #dbe1e9;white-space:nowrap;text-align:left}
th{position:sticky;top:0;background:#183553;color:white;z-index:1}td:nth-child(n+5):nth-child(-n+8){text-align:right}
tbody tr:nth-child(even){background:#f0f4f9}#status{color:#39516c}
@media print{.toolbar{display:none}.scroll{overflow:visible;max-height:none}body{padding:0;background:white}}
</style></head><body><h1>WAHIS 연도별 발생건수·추정 관찰기간</h1>
<p>연도별 계산 결과를 한 표에 모았습니다. HPAI 가금·가금 외 결과는 별도로 표시합니다.<br>
발생건수는 해당 조회기간 내 건수이며, 관찰구간 수에는 전년도 이월 구간이 포함됩니다.<br>
발생일 간격이 기준 일수를 초과하면 별도 구간으로 구분하고 발생일을 포함한 기준 일수의 관찰기간을 적용합니다.
연도별 조회기간 안의 관찰일을 계산하며 비율은 해당 조회 일수 대비 값입니다.<br>
실제 감염 지속기간이 아닌 시작일 기준 추정 관찰기간입니다. 링크는 1시간 유효하며 서버 재시작 시 만료될 수 있습니다.</p>
<details><summary>조회 조건과 연도별 기간</summary>''' + '<br>'.join(e(s) for s in summaries) + '''</details>
<div class="toolbar"><label>국가·질병 검색 <input id="search" type="search" placeholder="Japan, HPAI 등"></label>
<button id="copy">표 복사 (Excel 붙여넣기)</button><button id="download">TSV 다운로드</button><span id="status" role="status"></span></div>
<div class="scroll"><table id="results"><thead><tr>''' + ''.join(f'<th scope="col">{e(h)}</th>' for h in headers) + '''</tr></thead><tbody>''' + body + r'''</tbody></table></div>
<script>
const table=document.getElementById('results'),status=document.getElementById('status');
function selectedRows(){return [...table.querySelectorAll('tbody tr:not([data-empty])')].filter(r=>!r.hidden)}
function update(){status.textContent=selectedRows().length.toLocaleString()+'행'}
document.getElementById('search').addEventListener('input',e=>{const q=e.target.value.toLowerCase();table.querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));update()});
function tsv(){return [table.tHead.rows[0],...selectedRows()].map(r=>[...r.cells].map(c=>c.textContent.replace(/[\t\r\n]+/g,' ')).join('\t')).join('\r\n')}
document.getElementById('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(tsv());status.textContent=selectedRows().length.toLocaleString()+'행 복사 완료'}catch(e){status.textContent='복사 권한을 확인하거나 TSV 다운로드를 이용해 주세요.'}});
document.getElementById('download').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob(['\ufeff'+tsv()],{type:'text/tab-separated-values;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='wahis-yearly-observation.tsv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});update();
</script></body></html>'''
