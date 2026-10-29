# 보고서별 Streamlit 대시보드

## 현재 운영 상태 (2026-10-29)

[보고서 화면 예시](https://wahis-report-dashboard.onrender.com/?report_id=186834)

Render의 별도 무료 서비스 `wahis-report-dashboard`를 Oregon 리전에 직접 생성했고
공개 health HTTP 200 및 실제 보고서 DB 조회·지도·추이·목록 생성을 확인했다.
GitHub Actions의 `STREAMLIT_DASHBOARD_URL` 변수도 설정·재조회 확인했다.
다음 신규 보고서 알림부터 버튼이 붙으며 기존 메시지에는 소급 추가되지 않는다.
실제 신규 Slack 알림의 버튼 사용 확인은 아직 남아 있다.

실제 서비스는 MCP 직접 생성으로 관리한다. 아래 render.yaml은 재현용 참고이며
현재 서비스를 Blueprint로 등록한 것이 아니다. 서비스 자체의 health 검사는 기본 TCP이고
`/_stcore/health` HTTP 응답은 별도로 확인했다.

Slack 신규 보고서 알림에서 해당 Report ID의 발생 위치와 동일 국가·질병의 발생 추이를 연다.
기존 HTML 통계 대시보드는 유지한다.

## 로컬 실행

```powershell
python -m pip install -r requirements-dashboard.txt
python -m streamlit run streamlit_app.py
```

로컬 확인 주소는 `http://localhost:8501/?report_id=<저장된 보고서 ID>`이다.
기존 DB 환경변수와 TLS 설정을 사용한다. 앱은 DB 조회만 하며 수집이나 알림 발송을 실행하지 않는다.
새로고침 또는 `최신 DB 내용 조회` 버튼으로 다시 조회한다. 자동 주기 갱신은 이번 범위에 포함하지 않았다.

## 배포와 Slack 연결

Render Blueprint 설정은 저장소 루트의 [render.yaml](../render.yaml)에 있다.
새 `wahis-report-dashboard` 무료 Web Service 하나만 정의하며 기존 Slack 봇은 변경하지 않는다.
Render에서 이 저장소로 Blueprint를 생성하고 아래 DB 값들을 설정한다.
무료 서비스는 유휴 상태에서 중지될 수 있어 첫 접속이 지연될 수 있다.
참고: [Render Blueprint](https://render.com/docs/blueprint-spec), [무료 서비스 제한](https://render.com/docs/free).

Streamlit은 기존 Slack 봇과 별도 서비스로 실행한다.

- 설치 명령: `python -m pip install -r requirements-dashboard.txt`
- 실행 명령: `python -m streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port $PORT`
  (`$PORT`는 호스팅 서비스가 제공하는 포트 환경변수다.)
- Streamlit 서비스에 기존 DB 접속·TLS 환경변수를 설정한다. 가능하면 조회 전용 DB 계정을 사용한다.
- Slack 알림 발송 프로세스에 `STREAMLIT_DASHBOARD_URL=https://<배포한-대시보드-주소>`를 설정한다.
  이 설정이 없거나 HTTPS 주소가 아니면 기존 알림만 발송한다.
- 새 알림에 `발생 지도·추이 보기` 버튼이 추가된다. 기존 메시지는 자동 변경되지 않는다.

현재 신규 보고서 알림은 GitHub Actions의 `WAHIS Monitor`가 발송한다.
배포 URL이 확정되면 GitHub 저장소의 Settings → Secrets and variables → Actions → Variables에
`STREAMLIT_DASHBOARD_URL`을 HTTPS 주소로 추가한다. 워크플로가 이를 환경변수로 전달하므로
기존 전체 `SLACK_MONITOR_ENV` Secret을 교체할 필요가 없다.
이 워크플로에서는 Variables 설정이 우선이며 값이 없으면 버튼을 추가하지 않는다.
Render 봇에만 URL을 추가해서는 Actions 알림에 적용되지 않는다.

Streamlit 서비스에는 DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME,
DB_SSL_CA_CONTENT(인증서 PEM 내용)를 설정한다. 로컬 파일 경로인 DB_SSL_CA는 복사하지 않는다.
대시보드는 Slack 토큰·웹훅·B2 키를 사용하지 않으므로 해당 값은 전달하지 않는다.
배포 후 `/_stcore/health`와 실제 보고서 화면을 확인하고 GitHub Variable을 설정한다.
알림 발송 검증은 자동 운영 알림의 버튼으로 확인하며 검증용 수집 실행은 하지 않는다.

이 앱 자체에는 로그인 기능이 없다. 공개 배포하면 주소를 아는 사람이 저장된 Report ID를
조회할 수 있으므로, 조직 내부 용도라면 호스팅의 접근 제한을 적용한다.
Streamlit은 별도 배포 전까지 운영에서 사용할 수 없으며 기존 봇 배포만으로 실행되지 않는다.

## 해석 기준과 한계

- 지도: 최초 등록 보고서 또는 현재 최신 갱신 보고서가 선택한 Report ID인 발생지만 표시한다.
  주황은 신규, 파랑은 기존 발생 갱신이다. 동일한 크기의 원은 확산 반경을 의미하지 않는다.
- 좌표 누락·범위 초과는 지도에서 제외하고 상세 목록에 남긴다. 근사 위치 원본 플래그도 표시한다.
- 위치가 겹치는 원은 중첩될 수 있다. 지도 아래 목록에서 개별 발생을 확인한다.
- 과거 보고서별 전체 갱신 이력을 저장하지 않아 이후 재갱신된 지점은 과거 보고서 지도에서
  빠질 수 있다. 좌표·발생일 역시 현재 DB 값이며 과거 스냅샷을 보장하지 않는다.
- 추이: 보고서 제출일까지 30/90/365일, 동일 국가·질병의 발생일 기준 고유 발생 ID 집계다.
  후속 보고 수를 발생 건수로 세지 않으며 축종·사육·야생 수집 여부로 필터링하지 않는다.
- 과거 발생 자체가 미수집이거나 발생일이 없으면 추이에 포함되지 않는다.
- 축종·사육·야생은 기존 알림과 같은 보고서별 확인 범위로 표시한다. 과거 비율 비교는 하지 않는다.
- 배경 지도는 외부 지도 타일 서비스가 필요하므로 네트워크 장애 시 목록으로 확인한다.

지도 API 참고: [Streamlit st.map](https://docs.streamlit.io/develop/api-reference/charts/st.map).
원 크기·툴팁은 [st.pydeck_chart](https://docs.streamlit.io/develop/api-reference/charts/st.pydeck_chart)로 구성한다.

## 로컬 실제 데이터 검증 (2026-10-29)

최근 보고서 12건의 신규 발생 건수와 90일 추이 합계를 독립 SQL로 대조해 일치함을 확인했다.
실제 DB를 사용하는 Streamlit AppTest에서도 보고서 2건이 오류 없이 실행됐다.
이는 로컬 검증이며 공개 배포와 Slack 실사용 완료를 의미하지 않는다.
