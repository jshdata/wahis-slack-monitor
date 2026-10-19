# WAHIS Slack Monitor

WOAH(세계동물보건기구) **WAHIS**에 새로 등록되는 동물질병 리포트를 자동으로 감지해 DB에 저장하고, Slack으로 알림과 조회·통계 기능을 제공하는 프로젝트입니다.

## 모니터링 대상 질병

| 약어 | 질병 |
|------|------|
| HPAI | 고병원성 조류인플루엔자 (가금 / 가금 외 포함 야생조류) |
| ASF | 아프리카돼지열병 |
| FMD | 구제역 |
| LSD | 럼피스킨병 |
| BSE | 소해면상뇌증 |

수집 요청·API 응답·DB 저장 단계에서 이 5종만 허용합니다. HPAI는 가금·가금 외를 모두 포함합니다.
빈 질병 필터는 전체 질병 조회로 해석될 수 있어 거부하며, 비대상 질병이 응답에 포함되면 저장 전에 오류로 중단합니다.

## 주요 기능

- **신규 리포트 자동 감지**: WAHIS API를 페이지 단위로 조회하고, DB에 없는 Report만 신규로 판별
- **상세정보 적재**: Report별 상세 API로 subtype, outbreak, 정량 데이터(발생·폐사·살처분 등)를 저장
- **실패 자동 복구**: `detail_loaded = 0`으로 남은 Report를 다음 실행 때 재처리 (최대 10건)
- **Slack 알림**: 신규 Report 발견 시 Incoming Webhook으로 Block Kit 알림 전송
- **Slack 조회 (`/wahis`)**: 권역·국가·사육/야생·질병·기간(KST)으로 Report 검색
- **Slack 통계 (`/wahis-stats`)**: outbreak 발생일 기준 국가별 총 발생건수, 국가 × 세부질병(subtype) Matrix

BSE의 WAHIS 질병 ID는 `89`입니다. 기본 수집 대상에 포함되며, 과거 자료만 추가 적재할 때는 다음 명령을 사용합니다.

```powershell
python backfill_disease.py --disease BSE
```

이 명령은 과거 보고서와 상세 정보를 적재하며 Slack 알림을 생성하지 않습니다. 상세 적재가 완료된 보고서는 재실행 시 건너뜁니다.

## 국가별 연도·월 발생 여부 표

`/wahis-stats`의 PDF 보기 옆 **발생 여부 표 (O)**를 누르면 질병과 표시 단위(연도별·월별·둘 다)만 선택하여 HTML 표를 엽니다.

- 기간은 최초 발생 연도부터 한국시간 오늘까지이며, DB에 등록된 모든 국가를 포함합니다.
- 같은 국가·기간에 발생 기록이 한 건 이상 있으면 `O`, 없으면 공백입니다. 공백은 발생 기록이 없음을 뜻합니다.
- 권역은 국가 행을 병합하고, 월별 표는 연도 제목을 병합합니다. 북미·남미는 아메리카로 묶습니다.
- 마지막 열은 국가별 O 합계, 마지막 행은 날짜별 O 합계와 총 O 합계입니다. 연도별와 월별 합계는 각각 계산합니다.
- HPAI는 가금·가금 외를 별도 표로 표시합니다. DM 알림은 전송하지 않으며, 기존 Railway 표 서버와 1시간 링크를 사용합니다.

## 주변국 발생현황

`/wahis-stats`의 **주변국 발생현황**을 누르면 질병·시작일·종료일로 고정 18개국을 조회합니다.

- 네팔, 동티모르, 라오스, 말레이시아, 몽골, 미얀마, 방글라데시, 베트남, 부탄, 북한, 스리랑카, 싱가포르, 인도, 인도네시아, 중국(본토·홍콩 합산), 캄보디아, 태국, 필리핀을 포함합니다.
- 표는 **국가 | 발생건수 | 최근 발생일**이며 발생일 기준 고유 outbreak를 집계합니다. 발생 기록이 없는 국가도 0건으로 표시합니다.
- 최근 발생일은 선택한 기간 내 마지막 발생일입니다. 날짜를 비우면 18개국의 해당 질병 최초 발생일부터 오늘(한국시간)까지 조회합니다.
- HPAI는 가금·가금 외를 별도로 표시하며, 모달의 **큰 표 열기**로 HTML에서도 볼 수 있습니다. DM은 전송하지 않습니다.

## 배포 구조

```
cron-job (10분마다) ──▶ GitHub Actions ──▶ main.py ──▶ Aiven MySQL
                                                  └──▶ Slack Webhook 알림

Railway (상시 실행) ──▶ slack/query_app.py ◀──▶ Slack (/wahis, /wahis-stats)
                                  └──▶ Aiven MySQL
```

| 구성 요소 | 역할 |
|-----------|------|
| cron-job | 10분마다 GitHub API(`workflow_dispatch`)를 호출해 모니터링 실행 |
| GitHub Actions | `main.py` 실행 (신규 리포트 탐지·저장·알림) |
| Railway | Slack 조회·통계 봇(`slack/query_app.py`) 상시 실행 |
| Aiven | MySQL 데이터베이스 (SSL 연결) |

## 동작 흐름

```
WAHIS API → 신규 Report 판별 → 기본정보 저장 → 상세정보 저장 → Slack 알림
                                    (MySQL)      (재시도 5회)
```

1. 이전 실행에서 실패한 상세정보 복구
2. 최신 페이지부터 조회, 한 페이지가 전부 기존 데이터면 중단
3. 신규 Report의 기본정보 → 상세정보 순으로 저장
4. 상세정보 성공 여부와 관계없이 Slack 알림 발송

## 프로젝트 구조

```
wahis-slack-monitor/
├── main.py                  # 신규 리포트 탐지·저장·알림 (운영 진입점)
├── initial_load.py          # 전체 Report 기본정보 초기 적재
├── detail_initial_load.py   # 상세정보 배치 적재 (HPAI 가금 외)
├── wahis/
│   ├── api.py               # 이벤트 목록 API
│   └── detail_api.py        # Report 상세 API
├── database/
│   ├── db.py                # MySQL(Aiven) 연결, 기본정보 저장
│   ├── detail_db.py         # 상세정보 저장 (outbreaks, quantitative)
│   ├── query_db.py          # /wahis 검색 쿼리
│   └── stats_db.py          # /wahis-stats 통계 쿼리
├── slack/
│   ├── notifier.py          # 신규 Report 알림 (Webhook)
│   └── query_app.py         # 슬래시 커맨드 앱 (Socket Mode)
├── scheduler/               # 스케줄러 (준비 중)
├── config/                  # 설정 (준비 중)
└── .github/workflows/
    └── wahis-monitor.yml    # GitHub Actions 워크플로
```

## 기술 스택

- Python 3.12
- DB: Aiven MySQL (SSL 연결) / PyMySQL
- Slack: Bolt (Socket Mode), Incoming Webhook
- 실행 환경
  - 신규 리포트 모니터링: GitHub Actions (cron-job이 10분마다 트리거)
  - Slack 조회·통계 봇: Railway 상시 실행

## 설치 및 실행

```bash
pip install -r requirements.txt
```

`.env` 파일에 아래 값을 설정합니다.

```
DB_HOST=
DB_PORT=
DB_USER=
DB_PASSWORD=
DB_NAME=
DB_SSL_CA=            # 로컬: ca.pem 경로
DB_SSL_CA_CONTENT=    # 클라우드: ca.pem 내용
SLACK_WEBHOOK_URL=
SLACK_BOT_TOKEN=
SLACK_APP_TOKEN=
```

```bash
python initial_load.py          # 1. 기본정보 초기 적재 (최초 1회)
python detail_initial_load.py   # 2. 상세정보 배치 적재
python main.py                  # 3. 신규 리포트 모니터링
python -m slack.query_app       # 4. Slack 슬래시 커맨드 앱 실행
```

## 운영 가이드

### 신규 리포트 모니터링 (GitHub Actions + cron-job)

외부 cron-job 서비스가 10분마다(`*/10 * * * *`, Asia/Seoul) 아래 엔드포인트를 `POST`로 호출하고, 워크플로는 `python main.py`를 실행합니다.

```
https://api.github.com/repos/jshdata/wahis-slack-monitor/actions/workflows/wahis-monitor.yml/dispatches
```

필요한 Repository Secrets:

- `SLACK_MONITOR_ENV`: `.env` 전체 내용
- `DB_SSL_CA_CERT`: Aiven CA 인증서(`ca.pem`) 내용

cron-job 호출용 GitHub 토큰(fine-grained):

- 대상 저장소: `wahis-slack-monitor` 한 곳
- 권한: `Actions: Read and write`, `Metadata: Read`
- 만료일: 2026-12-10 (만료 전 갱신 필요 → cron-job의 `Authorization` 헤더도 함께 교체)

### 검색 가능한 다중 선택 필터

조회·통계의 질병·권역·국가와 조회의 사육 구분은 여러 항목을 검색해 선택할 수 있습니다.
발생 여부 표와 WOAH 문서의 질병 선택도 복수 선택을 지원합니다. 주변국 화면의
필터는 기존 단일 선택을 유지하며, 통계에서 진입할 때 첫 번째 질병만 초기값으로 사용합니다.

- 아무 항목도 선택하지 않으면 전체입니다. 같은 필터 안의 선택값은 OR,
  질병·권역·국가 등 서로 다른 필터는 AND로 적용합니다.
- Slack 국가 필터는 외부 검색 메뉴를 사용합니다. 처음에는 최대 100개 후보를
  표시하지만, 국가명을 입력하면 그 밖의 국가도 검색할 수 있습니다.
  권역 변경 시 입력한 날짜와 기존 국가·질병 선택은 유지됩니다.
- 통계에서 여러 질병을 선택하면 질병별 결과를 한 결과창에 모읍니다.
  HPAI의 가금·가금 외 구분과 연도별 관찰기간 계산은 그대로 적용됩니다.
- 대시보드의 질병·권역·국가, 주간 HTML의 국가·날짜·질병 필터는 검색·체크박스·
  선택 태그 방식입니다. 태그에서 개별 해제하거나 전체로 초기화할 수 있습니다.
- 권역·질병을 바꿔도 선택한 국가는 자동으로 해제되지 않습니다.
  선택한 권역과 국가가 일치하지 않으면 해당 조건의 결과는 0건일 수 있습니다.
- 날짜 범위, 시간, 조회 형태, 집계 단위, 그래프 종류는 기존 방식을 유지합니다.

Slack 모달은 다시 열고, 대시보드·주간 HTML은 새로 생성해야 새 필터가 적용됩니다.

### 수집 오류 유지보수 알림

`main.py` 실행 중 목록 API·기존 리포트 DB 조회·기본정보 저장·상세정보 적재·
Slack 전송·전송 상태 기록·자동 복구에서 오류가 발생하면 실행 종료 또는 중단 시
Slack으로 유지보수 알림을 보냅니다. 처리되지 않은 예외는 알림 후 다시 발생시켜
GitHub Actions 실패 상태와 원본 traceback을 유지합니다.

- 단계, 예외 종류·내용, 최초 발생시각(KST), 관련 report ID·국가·질병 또는 페이지,
  traceback 일부와 GitHub Actions 실행 로그 버튼을 포함합니다.
- 상세정보 적재는 기존 재시도를 모두 소진한 경우만 알립니다. 재시도 중 복구된
  일시 오류는 유지보수 알림을 보내지 않습니다.
- 동일 오류는 실행 내에서 묶고 최대 8종류·종류별 관련 정보 3개를 수록합니다.
  초과 오류는 건수만 표시하며 전체 내용은 원래 실행 로그에서 확인합니다.
  서로 다른 10분 주기 실행 사이의 알림은 별도로 발송합니다.
- 기본 채널은 기존 `SLACK_WEBHOOK_URL`입니다. 별도 채널로 보내려면
  `SLACK_ERROR_WEBHOOK_URL`을 `SLACK_MONITOR_ENV` Secret의 환경설정에 추가합니다.
- 알림은 DB에 의존하지 않으며, 비밀번호·토큰·웹훅 등은 Slack으로 보내기 전에 가립니다.
  Slack 자체 장애나 웹훅 오류로 유지보수 알림도 실패하면 콘솔에 실패를 남기며,
  알림 재귀 호출이나 원래 오류 덮어쓰기를 하지 않습니다.
- 오류가 없는 실행에서는 유지보수 알림을 보내지 않습니다. 프로세스 강제 종료나
  Python 실행 이전의 Actions 설치 단계 실패는 이 알림의 대상이 아닙니다.

### 주간 신규 리포트 요약

`.github/workflows/wahis-weekly.yml`은 매주 목요일 서울시간 오전 9시
(`0 0 * * 4`, UTC)에 실행됩니다. 먼저 기존 모니터를 실행해 최신 리포트를
수집한 다음, 기존 `SLACK_WEBHOOK_URL` 채널로 주간 요약을 전송합니다.
기존 `SLACK_MONITOR_ENV`, `DB_SSL_CA_CERT` Secrets를 그대로 사용합니다.
워크플로가 기본 브랜치에 반영되어야 자동 실행됩니다. GitHub Actions의
대기열과 수집 소요시간에 따라 실제 전송시각은 늦어질 수 있습니다.

- 집계 범위: 전주 목요일 09:00:00 이상 ~ 이번 목요일 09:00:00 미만 (KST).
  즉, 이번 목요일 08:59:59까지이며 매주 누락이나 중복되는 경계가 없습니다.
- 신규 여부는 DB 적재시각이 아닌 WAHIS `submission_date` 기준입니다.
  전체 질병의 최초·후속 리포트를 포함하며, 발생건수와 구분해 표시합니다.
- Slack에는 전체 리포트·국가·질병 수, 최초·후속 리포트 수, 추가 발생건수와
  **주간 상세 HTML 보기** 버튼 하나를 보냅니다. 리포트가 없는 주도 0건 알림을 보냅니다.
- 상세 HTML에서 날짜별·국가별 보기를 전환하고, 국가·날짜로 필터링할 수 있습니다.
  각 그룹에는 보고 유형·발생 사유·제출시각·아형·이벤트 상태·원문 링크를 표시합니다.
- 추가 발생은 `outbreaks.created_by_report_id`가 해당 리포트인 고유 outbreak 수입니다.
  기존 outbreak 수정은 추가 발생에 포함하지 않습니다. 상세 미수집 리포트는
  발생건수 합계에서 제외하고 미확인으로 표시합니다.
- 최초·후속은 WAHIS의 `IN`/`FUR` 또는 보고 차수(0=최초, 1 이상=후속)로 구분합니다.
- HTML은 `weekly_html_reports` 테이블(최초 전송 시 자동 생성)에 90일 보관됩니다.
  임의 토큰을 포함한 링크를 가진 사람이 열 수 있습니다. 만료된 데이터는 다음 전송 시 정리합니다.
- 기존 Railway 앱의 HTML 서버가 `/weekly/<token>` 경로를 제공합니다.
  워크플로와 Railway 양쪽에 최신 코드가 반영되어야 상세 버튼이 동작합니다.
  기본 주소는 `https://wahis-slack-monitor-production.up.railway.app`이며,
  변경 시 `WEEKLY_REPORT_BASE_URL` 또는 `STATS_REPORT_BASE_URL`을 설정합니다.
- 조회 시점에 DB에 수집된 리포트가 대상입니다. 늦게 공개·수집된 과거 리포트는
  다음 주 집계로 넘어가지 않으므로 필요한 경우 해당 주를 수동 재실행합니다.
- Actions의 **WAHIS Weekly Digest → Run workflow**에서 미리보기를 실행할 수
  있습니다. `dry_run` 기본값은 true이며, 실제 재전송하려면 false로 설정합니다.
  `week_ending`에 종료 목요일을 지정할 수 있습니다. 재실행은 요약을 다시 전송합니다.
  미리보기 HTML은 실행 결과의 `weekly-html-preview` artifact에서 다운로드합니다.

로컬 미리보기 (Slack 전송 없음):

```bash
python weekly_main.py --dry-run
python weekly_main.py --week-ending 2026-10-22 --dry-run --output data/weekly_preview.html
```

### Slack 조회·통계 봇 (Railway)

`python -m slack.query_app`을 Railway에서 상시 실행합니다. 로컬 `.env` 대신 Railway 환경변수를 사용하며, CA 인증서는 파일 대신 `DB_SSL_CA_CONTENT`에 내용을 넣습니다.

Matrix 결과 모달의 **큰 표 열기**는 HTML 표를 브라우저로 바로 엽니다. DM이나 파일 업로드를 사용하지 않습니다.

- Railway 서비스의 **Settings → Networking → Public Networking → Generate Domain**에서 공개 도메인을 생성합니다.
- 앱은 `PORT` 환경변수의 포트에서 표를 제공하며, 기본 포트는 `8765`입니다. 도메인의 대상 포트를 앱 포트와 맞춥니다.
- `RAILWAY_PUBLIC_DOMAIN`을 자동으로 사용합니다. 별도 도메인은 `STATS_REPORT_BASE_URL=https://도메인`으로 지정할 수 있습니다.
- 상태 확인 경로는 `/health`입니다. 로컬에서는 기본적으로 `http://localhost:8765`를 사용합니다.
- 표 링크는 임의 토큰으로 생성되며 링크를 가진 사람이 열 수 있습니다. 결과는 메모리에 보관되고 1시간, 앱 재시작 또는 최근 결과 30개 초과 시 만료됩니다. 단일 봇 인스턴스에서 실행합니다.
- 이 기능에는 `files:write`, `im:write` 권한이 필요하지 않습니다.

### 통계 대시보드 (Plotly)

`/wahis-stats` 상단의 **통계 대시보드** 버튼을 누르면 브라우저에서 열 수 있는
대시보드 링크가 생성됩니다. Slack에서 선택한 질병·권역·국가·날짜를 가져오며,
기간 미선택 시 올해를 기본으로 표시합니다. 링크는 기존 HTML 서버에서 1시간 제공됩니다.

- 질병·권역·국가·기간 필터, 일별·월별·연도별 집계를 지원합니다.
- 기간별 추세, 전년 동기 비교, 질병별 비중, 국가·권역별 발생건수를 표시합니다.
- 꺾은선·막대·원·도넛그래프를 전환하고, 그래프 이미지와 상세 집계 CSV를 저장할 수 있습니다.
- 발생일 기준 고유 outbreak를 집계합니다. 이벤트별 보고 메타데이터를 한 번만 사용해
  후속 리포트가 중복 발생으로 계산되지 않도록 합니다. SQL 임시 집계표 없이 순차 조회합니다.
- 전년 동기는 시작·종료일을 1년 전으로 이동합니다. 2월 29일은 2월 28일로 조정합니다.
  전년 0건이면 증감률을 계산하지 않습니다. 일별 조회는 최대 4,000일입니다.
- Python은 DB 집계, HTML/CSS는 화면, Plotly.js는 그래프를 담당합니다.
  Plotly 스크립트는 설치된 Python 패키지에서 기존 서버를 통해 제공하므로 외부 CDN에 의존하지 않습니다.
- 페이지는 생성 시점의 자료 사본입니다. 필터는 브라우저에서 동작하며,
  최신 자료는 Slack에서 대시보드를 다시 생성해 확인합니다.

Railway에서 `requirements.txt`의 Plotly 의존성과 최신 코드가 배포되어야 동작합니다.

## 참고

- DB의 시간은 UTC로 저장되며, Slack 조회 시 KST로 변환합니다.
- `.env`, `*.pem` 등 민감 파일은 `.gitignore`로 제외됩니다.

# PDF object storage

For setup and migration, see the [Railway PDF guide](docs/railway-pdf-storage.md)
or the [Cloudflare R2 PDF guide](docs/r2-pdf-storage.md).

## ntfy 동시 알림

기존 `SLACK_MONITOR_ENV` GitHub Actions secret의 마지막에 다음 줄을 추가하면
Slack과 ntfy에서 신규 WAHIS 보고 알림을 함께 받을 수 있습니다.

```dotenv
NTFY_TOPIC_URL=https://ntfy.sh/여기에-구독한-주제
# 인증이 필요한 서버/토픽에서만 설정
# NTFY_TOKEN=토큰
```

로컬 실행은 `.env`에 같은 설정을 추가합니다. 설정이 없으면 ntfy는 비활성화됩니다.
첫 실행에서 `ntfy_outbox` 테이블을 자동 생성하므로 DB 계정에 CREATE TABLE 권한이
필요합니다. 활성화 이후 새로 저장되는 보고만 전송하며 과거 보고를 일괄 발송하지 않습니다.
Slack 전송 상태와 별도로 관리하며, 실패 건은 다음 실행에서 재시도합니다(최대 5회).
전송 성공 직후 DB 기록이 실패하면 중복 수신할 수 있습니다.
