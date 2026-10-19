"""Browser table for all matching control measures, 100 rows per page."""
from html import escape
from wahis import control_storage


def build_report(filters, query):
    try:
        page = max(0, int(query.get('page', ['0'])[0]))
    except (TypeError, ValueError, IndexError):
        page = 0
    data = control_storage.query(filters, page, page_size=100)
    page, total = data['page'], data['total']
    pages = max(1, (total + 99) // 100)
    def e(value):
        return escape(str(value if value is not None else ''))
    year = filters.get('year', 'all')
    year = '전체 연도' if year == 'all' else year
    semester = {'1': '상반기', '2': '하반기'}.get(filters.get('semester'), '전체 반기')
    scope = {'vaccination': '접종 시행·금지', 'official': '공식 예방접종만'}.get(filters.get('scope'), '모든 방역 조치')
    columns = [('year', '연도'), ('semester', '반기'), ('region', '권역'), ('country', '국가'),
               ('disease', '질병·적용 범위'), ('category', '동물 분류'), ('species', '종'), ('measure', '방역 조치')]
    rows = ''.join('<tr>' + ''.join(f'<td>{e(row[key])}</td>' for key, _ in columns) + '</tr>' for row in data['rows'])
    if not rows:
        rows = '<tr><td colspan="8">해당 조건의 보고 항목이 없습니다. 조치 미시행을 뜻하지 않습니다.</td></tr>'
    nav = f'<span>{page + 1:,} / {pages:,} 페이지</span>'
    for title, number in [('처음', 0), ('이전', page - 1), ('다음', page + 1), ('마지막', pages - 1)]:
        if 0 <= number < pages and number != page:
            nav += f'<a href="?page={number}">{title}</a>'
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">
<title>방역 조치 조회</title><style>
*{{box-sizing:border-box}}body{{font-family:system-ui,sans-serif;margin:0;background:#f3f6fa;color:#172b45}}
main{{max-width:1500px;margin:auto;padding:28px 20px}}h1{{font-size:26px;margin:0 0 14px}}
.card{{background:white;border:1px solid #dce3ed;border-radius:12px;padding:18px;margin-bottom:18px}}
.meta{{color:#506278;line-height:1.7}}nav{{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin:16px 0}}
a{{padding:8px 14px;border:1px solid #ccd8e9;border-radius:7px;text-decoration:none;color:#1756a0;background:white}}
.table{{overflow:auto;background:white;border:1px solid #dce3ed;border-radius:10px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:12px;text-align:left;border-bottom:1px solid #e4eaf2;vertical-align:top}}
th{{background:#e9f0f9;white-space:nowrap}}tbody tr:nth-child(even){{background:#f7f9fc}}td:nth-child(5){{min-width:260px}}
@media print{{nav{{display:none}}body{{background:white}}main{{padding:0}}}}
</style></head><body><main><div class="card"><h1>방역 조치 조회 · {e(filters.get('disease'))}</h1>
<div class="meta">{e(year)} · {e(semester)} · {e(filters.get('country') or '전체 국가')} · {e(scope)}<br>
보고 항목 <strong>{total:,}건</strong> · 페이지당 최대 100건 · 전체 결과는 페이지를 이동해 확인할 수 있습니다.<br>
자료 수집 완료: {e(data['snapshot_at'])}<br>
국가·질병·반기별 보고된 조치이며 실제 시행 횟수·접종 마릿수·접종률이 아닙니다.
HPAI 가금·가금 외 구분은 질병·적용 범위 열에 표시합니다.</div></div>
<nav aria-label="페이지 이동">{nav}</nav><div class="table"><table><thead><tr>
{''.join('<th scope="col">' + e(title) + '</th>' for _, title in columns)}</tr></thead><tbody>{rows}</tbody></table></div>
<nav aria-label="페이지 이동">{nav}</nav><p class="meta">링크는 생성 후 1시간 동안 유효하며 서버 재시작 시 만료될 수 있습니다.</p>
</main></body></html>'''
