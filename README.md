# WAHIS Slack Monitor

WOAH(세계동물보건기구) **WAHIS**에 새로 등록되는 동물질병 리포트를 자동으로 감지해 DB에 저장하고, Slack으로 알림과 조회·통계 기능을 제공하는 프로젝트입니다.

## 모니터링 대상 질병

| 약어 | 질병 |
|------|------|
| HPAI | 고병원성 조류인플루엔자 (가금 / 가금 외 포함 야생조류) |
| ASF | 아프리카돼지열병 |
| FMD | 구제역 |
| LSD | 럼피스킨병 |

## 주요 기능

- **신규 리포트 자동 감지**: WAHIS API를 페이지 단위로 조회하고, DB에 없는 Report만 신규로 판별
- **상세정보 적재**: Report별 상세 API로 subtype, outbreak, 정량 데이터(발생·폐사·살처분 등)를 저장
- **실패 자동 복구**: `detail_loaded = 0`으로 남은 Report를 다음 실행 때 재처리 (최대 10건)
- **Slack 알림**: 신규 Report 발견 시 Incoming Webhook으로 Block Kit 알림 전송
- **Slack 조회 (`/wahis`)**: 권역·국가·사육/야생·질병·기간(KST)으로 Report 검색
- **Slack 통계 (`/wahis-stats`)**: outbreak 발생일 기준 국가별 총 발생건수, 국가 × 세부질병(subtype) Matrix

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

### Slack 조회·통계 봇 (Railway)

`python -m slack.query_app`을 Railway에서 상시 실행합니다. 로컬 `.env` 대신 Railway 환경변수를 사용하며, CA 인증서는 파일 대신 `DB_SSL_CA_CONTENT`에 내용을 넣습니다.

## 참고

- DB의 시간은 UTC로 저장되며, Slack 조회 시 KST로 변환합니다.
- `.env`, `*.pem` 등 민감 파일은 `.gitignore`로 제외됩니다.
