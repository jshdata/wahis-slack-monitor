"""Standalone, full-window Matrix reports with equal-width columns."""

from html import escape


def build_matrix_report(items):
    sections = []
    for item in items:
        if item['kind'] != 'matrix':
            continue
        rows = item['rows']
        column_count = len(rows[0])
        # Every column receives exactly 1/N of the table. Retain a readable
        # minimum width and scroll horizontally when there are many columns.
        columns = ''.join(f'<col style="width:{100 / column_count:.8f}%">'
                          for _ in rows[0])
        header = ''.join(f'<th scope="col">{escape(str(cell))}</th>' for cell in rows[0])
        body = []
        for row in rows[1:]:
            cells = ''.join(f'<td>{escape(str(cell))}</td>' for cell in row)
            css_class = 'total' if row[0] == 'TOTAL' else ''
            body.append(f'<tr class="{css_class}">{cells}</tr>')
        sections.append(
            f'<section><pre>{escape(item["text"])}</pre>'
            f'<div class="table-scroll"><table style="min-width:{column_count * 110}px">'
            f'<colgroup>{columns}</colgroup><thead><tr>{header}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div></section>')
    return '''<!doctype html>
<html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WAHIS Matrix</title>
<style>
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; color: #172033; background: #f4f6fa;
       font: 15px system-ui, sans-serif; }
header { display: flex; align-items: center; justify-content: space-between; }
button { padding: 10px 18px; cursor: pointer; }
section { margin: 20px 0 36px; }
pre { white-space: pre-wrap; font: inherit; line-height: 1.6; }
.table-scroll { max-height: 78vh; overflow: auto; border: 1px solid #ccd4df; }
table { width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0;
        font-variant-numeric: tabular-nums; background: white; }
th, td { padding: 12px 10px; border-right: 1px solid #dbe1e9;
         border-bottom: 1px solid #dbe1e9; text-align: right; }
th { position: sticky; top: 0; z-index: 2; background: #183553; color: white;
     text-align: center; overflow-wrap: anywhere; }
td { white-space: nowrap; }
th:first-child, td:first-child { position: sticky; left: 0; text-align: left; }
td:first-child { background: inherit; white-space: normal; overflow-wrap: anywhere; }
th:first-child { z-index: 3; }
tbody tr { background: white; }
tbody tr:nth-child(even) { background: #f0f4f9; }
th:last-child, td:last-child { font-weight: 700; }
tr.total { background: #dce9f7; font-weight: 700; }
</style>
<header><h1>WAHIS Matrix</h1><button id="fullscreen">전체 화면</button></header>
<p>각 열은 동일한 너비입니다. 열이 많으면 표를 좌우로 스크롤하세요. Total은 마지막 열입니다.</p>
''' + ''.join(sections) + '''
<script>
document.getElementById('fullscreen').addEventListener('click', async () => {
  if (document.fullscreenElement) await document.exitFullscreen();
  else await document.documentElement.requestFullscreen();
});
</script></html>'''
