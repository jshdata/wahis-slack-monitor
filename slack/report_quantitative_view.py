"""Render report totals and species comparisons with explicit scope and units."""
import logging
import altair as alt
import pandas as pd
import streamlit as st
from database.report_quantitative_dashboard import (
    FIELDS, load_report_quantities, quantity_summary, format_quantity, species_quantities,
)


def render_quantities(report_id):
    st.subheader('보고서 피해·대응 규모')
    st.caption('보고서 단위 정량자료입니다. 개별 발생지의 수치가 아니며 항목 간 중복이 가능해 합산하지 않습니다.')
    try:
        rows = load_report_quantities(report_id)
    except Exception as exc:
        logging.getLogger(__name__).warning('Report quantities unavailable: %s', type(exc).__name__)
        st.info('보고서 정량자료를 불러오지 못했습니다. 잠시 후 다시 조회해주세요.')
        return
    if not rows:
        st.info('저장된 보고서 정량자료가 없습니다. 미수집·미보고를 0으로 처리하지 않습니다.')
        return
    scope = st.radio('정량자료 범위', ['이번 보고', '누계'], horizontal=True, key='quantity_scope')
    data_type = 'new' if scope == '이번 보고' else 'total'
    selected = [r for r in rows if r['data_type'] == data_type]
    if not selected:
        st.info(f'{scope} 정량자료가 없습니다. 다른 범위의 수치로 대신 표시하지 않습니다.')
        return
    units = sorted({r['unit'] for r in selected})
    unit = st.selectbox('정량자료 단위(원본)', units, key='quantity_unit')
    selected = [r for r in selected if r['unit'] == unit]
    st.caption(f'{scope} · 원본 단위: {unit} · 단위가 다른 자료는 함께 합산하지 않습니다.')
    summary = quantity_summary(selected)
    columns = st.columns(3)
    for index, (field, label) in enumerate(FIELDS.items()):
        columns[index % 3].metric(label, format_quantity(summary[field]))
    chart_rows = [{'항목': label, '수량': summary[field]['value'],
                   '자료 상태': '일부 미보고' if summary[field]['missing'] else '보고됨'}
                  for field, label in FIELDS.items() if summary[field]['value'] is not None]
    if chart_rows:
        st.altair_chart(alt.Chart(pd.DataFrame(chart_rows)).mark_bar().encode(
            x=alt.X('수량:Q', title=f'수량 ({unit})'), y=alt.Y('항목:N', sort=list(FIELDS.values())),
            tooltip=['항목:N', '수량:Q', '자료 상태:N']).properties(height=280), use_container_width=True)
    st.caption('미보고는 0이 아닙니다. 일부 미보고가 있으면 숫자와 막대는 확인된 값의 합계만 나타냅니다.')
    st.subheader('축종별 피해·대응 상세 수치')
    table, comparisons = species_quantities(selected)
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)
    if len(table) > 1 and comparisons:
        # Facets compare independent metrics without suggesting additive stacks.
        comparison = alt.Chart(pd.DataFrame(comparisons)).mark_bar().encode(
            x=alt.X('수량:Q', title=f'수량 ({unit})'),
            y=alt.Y('축종·구분:N', title=None),
            tooltip=['축종·구분:N', '항목:N', '수량:Q', '자료 상태:N']
        ).properties(height=max(120, min(500, len(table) * 35 + 60))).facet(
            column=alt.Column('항목:N', title=None)).resolve_scale(x='independent')
        st.altair_chart(comparison, use_container_width=True)
    st.caption('이 표는 선택한 보고서·범위·단위의 축종별 정량자료입니다. 발생지별 축종 수집 현황과 자료 범위가 다를 수 있습니다.')
