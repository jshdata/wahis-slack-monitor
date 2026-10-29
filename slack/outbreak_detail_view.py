"""One detail panel shared by map selection and the outbreak dropdown."""
import streamlit as st
from slack.dashboard_interactions import csv_bytes


def render_outbreak_detail(rows, species_sites, key, export_rows, metadata, on_change=None):
    st.subheader('선택한 발생지 상세')
    selected_id = st.selectbox('발생지 상세 보기', [r['outbreak_id'] for r in rows], key=key,
                              on_change=on_change,
                              format_func=lambda oid: next(
                                  f"{r['outbreak_id']} · {r['location'] or r['admin_division'] or '위치명 미확인'}"
                                  for r in rows if r['outbreak_id'] == oid))
    site = next(r for r in rows if r['outbreak_id'] == selected_id)
    st.write(f"**발생 ID:** {selected_id} · **구분:** {site['kind']}")
    st.write(f"**지역:** {site['admin_division'] or '미확인'} · **위치:** {site['location'] or '미확인'}")
    st.write(f"**역학 단위:** {site.get('epi_unit_type') or '미확인'} · "
             f"**집단 발생 역학 단위 수:** {site.get('cluster_count') if site.get('cluster_count') is not None else '미확인'}")
    st.write(f"**시작일:** {site['start_date'] or '미확인'} · **종료일:** {site.get('end_date') or '미보고'}")
    classification = species_sites.get(selected_id, {})
    st.write(f"**축종:** {classification.get('species', '미확인')} · "
             f"**사육·야생:** {classification.get('category', '미확인')}")
    st.caption('발생지 상세는 현재 DB 상태입니다. 과거 보고서 당시의 스냅샷이 아닙니다. 종료일 미보고를 진행 중으로 단정하지 않습니다.')
    st.write('**발생지·역학 상황 원문 설명**')
    st.text(site.get('description') or '저장된 원문 설명이 없습니다.')
    st.download_button('선택한 발생지 상세 CSV 다운로드', csv_bytes(
        [r for r in export_rows if r['발생 ID'] == selected_id],
        {**metadata, '자료 범위': '선택 발생지 · 현재 DB 상태'}),
        file_name=f"wahis-report-{metadata['보고서 ID']}-outbreak-{selected_id}.csv", mime='text/csv')
