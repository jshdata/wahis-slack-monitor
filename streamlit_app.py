"""Run with: python -m streamlit run streamlit_app.py."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pydeck as pdk
import altair as alt
import streamlit as st

from database.report_dashboard_db import load_report_dashboard
from database.report_alert_details import get_report_alert_details
from slack.country_map import country_boundary
from database.report_species_dashboard import load_report_species

st.set_page_config(page_title='WAHIS 보고서 대시보드', page_icon='🌍', layout='wide')
st.title('WAHIS 보고서 대시보드')
try:
    report_id = int(st.query_params.get('report_id', '0'))
    if report_id <= 0:
        raise ValueError
except (ValueError, TypeError):
    st.info('Slack 보고서 알림의 대시보드 버튼으로 열어주세요.')
    st.stop()

days = st.radio('발생 추이 기간', [30, 90, 365], index=1, format_func=lambda d: f'{d}일', horizontal=True)
st.caption('기간은 보고서 제출일 기준입니다. 새로고침하면 현재 DB 내용을 다시 조회합니다.')
st.button('최신 DB 내용 조회')
try:
    data = load_report_dashboard(report_id, days)
except Exception as exc:
    logging.getLogger(__name__).warning('Report dashboard failed: %s', type(exc).__name__)
    st.error('데이터를 불러오지 못했습니다. 잠시 후 다시 조회해주세요.')
    st.stop()
if data is None:
    st.warning('저장된 보고서를 찾을 수 없습니다.')
    st.stop()

report, rows = data['report'], data['outbreaks']
st.subheader(f"{report['country']} · {report['disease']}")
st.write(f"Report {report_id} · Event {report['event_id']} · {report['report_type'] or '-'} · {report['event_status'] or '-'}")
st.write(f"제출일: {report['submission_date'] or '미확인'}")
details = get_report_alert_details({'reportId': report_id})
left, right = st.columns(2)
left.metric('이번 보고 신규 발생', details['new_outbreaks'])
right.metric('현재 DB에서 확인되는 기존 발생 갱신', sum(r['kind'] != '신규' for r in rows))
st.caption('과거 보고서의 갱신 이력 전체를 보관하지 않아, 이후 다시 갱신된 발생지는 이 지도에서 빠질 수 있습니다. '
           '위치·발생일은 현재 DB 값이며 당시 보고서의 스냅샷이 아닙니다.')
if report['detail_loaded'] != 1:
    st.warning('이 보고서의 상세 수집이 완료되지 않았습니다. 지도·건수가 불완전할 수 있습니다.')
st.write(f"혈청형·아형: {details['subtype']} | 사육·야생: {details['animal_category']} | 축종: {details['species']}")
st.caption('축종·사육·야생은 이번 보고로 갱신된 발생지의 확인된 자료 기준입니다. 미수집은 0이나 사육으로 처리하지 않습니다.')

st.subheader('이번 보고의 발생 위치')
points = [{'latitude': float(r['latitude']), 'longitude': float(r['longitude']),
           'outbreak_id': str(r['outbreak_id']), 'kind': r['kind'],
           'location': r['location'] or '위치명 미확인',
           'color': [249, 115, 22, 220] if r['kind'] == '신규' else [37, 99, 235, 220]}
          for r in rows if r['mapped']]
st.caption(f"확인되는 발생지 {len(rows)}곳 중 좌표가 유효한 {len(points)}곳 표시 · 주황: 신규 / 파랑: 기존 발생 갱신")
if points:
    boundary = country_boundary(report['country'])
    layers = []
    if boundary['features']:
        layers.append(pdk.Layer(
            'GeoJsonLayer', boundary, filled=True, stroked=True,
            get_fill_color=[20, 184, 166, 55], get_line_color=[13, 148, 136, 240],
            get_line_width=100, line_width_min_pixels=2, line_width_max_pixels=2,
            pickable=False))
        st.caption('청록색 면과 테두리: 보고서의 해당 국가 · 발생·위험 지역의 범위를 뜻하지 않습니다.')
    else:
        st.caption('해당 국가의 경계 자료를 연결하지 못해 발생 지점만 표시합니다.')
    layers.append(pdk.Layer('ScatterplotLayer', points,
                            get_position='[longitude, latitude]', get_fill_color='color',
                            get_radius=100, radius_min_pixels=7, radius_max_pixels=7,
                            pickable=True))
    view = pdk.data_utils.compute_view([[p['longitude'], p['latitude']] for p in points])
    view.zoom = max(1, min(view.zoom, 10))
    st.pydeck_chart(pdk.Deck(
        initial_view_state=view, map_style=None,
        layers=layers,
        tooltip={'text': '발생 ID: {outbreak_id}\n{kind}\n{location}'}))
else:
    st.info('표시할 좌표가 없습니다. 아래 목록에서 확인해주세요.')
st.caption('원의 크기는 동일하며 확산·위험 반경을 뜻하지 않습니다. 근사 위치는 아래 목록에서 구분합니다. '
           '같은 좌표의 원은 겹칠 수 있습니다.')
st.caption('국가 경계: Natural Earth 1:50m v5.1.2 · 지도 식별용 일반화 자료')

st.subheader('동일 국가·질병의 기간별 발생 건수')
if data['trend']:
    trend = pd.DataFrame(data['trend'])
    trend['발생일'] = pd.to_datetime(trend['발생일'])
    occurrences = trend[trend['발생 건수'] > 0]
    total = int(occurrences['발생 건수'].sum())
    st.metric(f'선택한 {days}일의 발생 합계', f'{total}건')
    if not occurrences.empty:
        dates = occurrences['발생일'].dt.strftime('%Y-%m-%d').tolist()
        st.write('**발생일:** ' + (dates[0] if len(dates) == 1 else
                 f'{dates[0]} ~ {dates[-1]} · 총 {len(dates)}일에 발생'))
        scale = alt.Scale(domain=[pd.Timestamp(data['start']).isoformat(),
                                  pd.Timestamp(data['end']).isoformat()])
        baseline = alt.Chart(pd.DataFrame([{'start': pd.Timestamp(data['start']),
                                           'end': pd.Timestamp(data['end'])}])).mark_rule(
                                               color='#94a3b8', strokeWidth=2).encode(
            x=alt.X('start:T', scale=scale, axis=alt.Axis(format='%m-%d', tickCount=6), title='발생일'),
            x2='end:T', y=alt.value(25))
        dots = alt.Chart(occurrences).mark_circle(size=110, color='#2563eb', opacity=1).encode(
            x=alt.X('발생일:T', scale=scale, axis=alt.Axis(format='%m-%d', tickCount=6), title='발생일'),
            y=alt.value(25),
            tooltip=[alt.Tooltip('발생일:T', format='%Y-%m-%d'), alt.Tooltip('발생 건수:Q', format='d')])
        st.altair_chart((baseline + dots).properties(height=90).configure_view(stroke=None),
                       use_container_width=True)
        st.caption('점 하나는 발생이 확인된 날짜입니다. 점에 마우스를 올리면 해당 날짜의 발생 건수를 볼 수 있습니다.')
    else:
        st.info('선택 기간에 DB에서 확인되는 발생이 없습니다.')
    st.caption(f"{data['start']} ~ {data['end']} · 발생일 기준 고유 발생 ID 집계 · 후속 보고 중복 제외 · "
               '축종·사육·야생 필터 미적용 · 미수집 발생 및 발생일 미상은 반영되지 않습니다.')
else:
    st.info('제출일이 없어 추이 기간을 정할 수 없습니다.')

st.subheader('이번 보고의 축종·사육·야생 현황')
species_sites = {}
try:
    species_data = load_report_species(report_id)
    # Align this enrichment to the same site set as the map/table snapshot.
    expected_ids = {r['outbreak_id'] for r in rows}
    if set(species_data['sites']) != expected_ids:
        raise ValueError('Outbreak set changed during dashboard query')
    species_sites = species_data['sites']
    if species_sites:
        for column, category in zip(st.columns(4), ('사육', '야생', '혼합', '미확인')):
            column.metric(f'{category} 발생지', f"{species_data['categories'][category]}곳")
        st.caption('현재 이 보고서에 연결되는 신규·갱신 발생지 기준입니다. 혼합은 사육·야생이 함께 확인된 발생지입니다. '
                   '분류 미수집·부분 미확인·보고서 버전 불일치는 미확인으로 표시합니다. 동물 마릿수가 아닙니다.')
        if species_data['species']:
            st.altair_chart(alt.Chart(pd.DataFrame(species_data['species'])).mark_bar().encode(
                x=alt.X('발생지 수:Q', axis=alt.Axis(tickMinStep=1, format='d'), title='발생지 수(곳)'),
                y=alt.Y('축종:N', sort='-x'), tooltip=['축종:N', '발생지 수:Q']
            ).properties(height=max(160, min(600, len(species_data['species']) * 32 + 80))),
                use_container_width=True)
            st.caption('같은 발생지에 여러 축종이 있으면 각 축종에 한 번씩 포함됩니다. 축종별 수를 더하면 전체 발생지 수와 다를 수 있습니다. '
                       '확인된 축종명만 그래프에 표시하며 미확인은 아래 목록에서 구분합니다.')
        else:
            st.info('이 보고서에서 확인되는 축종명이 없습니다.')
    else:
        st.info('현재 이 보고서에 연결되는 발생지가 없어 축종·사육·야생 현황을 표시할 수 없습니다.')
except Exception as exc:
    logging.getLogger(__name__).warning('Report species dashboard failed: %s', type(exc).__name__)
    st.info('축종·사육·야생 상세 자료를 불러오지 못했습니다. 미확인을 0건으로 처리하지 않습니다.')

st.subheader('발생지 상세 목록')
table = [{'발생 ID': r['outbreak_id'], '구분': r['kind'], '지역': r['admin_division'],
          '위치': r['location'], '근사 위치(원본)': str(r['location_approx']), '발생일': r['start_date'],
          '위도': r['latitude'], '경도': r['longitude'], '지도 표시': r['mapped'],
          '사육·야생': species_sites.get(r['outbreak_id'], {}).get('category', '미확인'),
          '축종': species_sites.get(r['outbreak_id'], {}).get('species', '미확인')} for r in rows]
if table:
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)
else:
    st.info('현재 DB에서 이 보고서와 연결되는 발생지가 없습니다. 발생이 없다는 뜻은 아닙니다.')
st.caption('조회 시각: ' + datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S KST'))
