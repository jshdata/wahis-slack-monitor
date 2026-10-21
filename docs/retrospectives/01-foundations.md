# 01. 반복 확인에서 자동 운영까지

[회고 목차](README.md) · 초기 날짜는 첨부 기록에서 확인되지 않는 한 확정하지 않습니다.

## RET-BASE-01 — 화면 수집보다 실제 요청을 먼저 확인했다

**상태: 완화·우회 운영 / 근거: 이전 기록, 현재 API 코드.**

WAHIS를 수동 확인하는 일을 줄이려면 먼저 데이터를 안정적으로 얻어야 했다.
초기 Python 요청에서 403이 발생했다. 이전 기록에서는 Cloudflare 등 앞단의 영향을
가능한 배경으로 설명하지만, 모든 403의 근본 원인을 입증한 것은 아니다.

브라우저 Network에서 실제 URL·POST 방식·payload·query parameter를 확인하고
`/api/v1/pi/event/filtered-list?language=en` 요청을 재현해 200 응답을 받았다.
처음부터 Selenium으로 화면을 반복 조작하는 대신 구조화된 JSON을 사용하는 쪽을 택했다.
페이지 구조에 덜 의존하고 DB로 옮길 필드를 직접 확인할 수 있었기 때문이다.

다만 브라우저에서 쓰는 공개 조회 경로가 영구적으로 보장되는 공식 API 계약이라는
뜻은 아니다. 전체 적재에서는 ConnectionReset·WinError 10054도 관찰했다.
후속 작업에서 재시도와 요청 간격을 추가했지만 네트워크 실패 자체를 제거하지는 못했다.

근거: [목록 API](../../wahis/api.py), [상세 API](../../wahis/detail_api.py).

## RET-BASE-02 — Event가 아니라 Report를 신규 알림의 기준으로 삼았다

**상태: 해결 / 근거: 이전 기록, 현재 기본 저장 코드.**

하나의 Event에 최초 보고와 여러 후속 Report가 연결된다.
Event가 이미 존재한다는 이유로 신규가 아니라고 처리하면 같은 이벤트의 후속 보고를 놓친다.
그래서 신규 탐지는 `report_id`로 하고 `event_id`는 보고서를 묶는 관계로 남겼다.

DB는 이전에 본 Report를 기억하는 역할을 한다. `report_id` 기본키와 UPSERT를 사용해
반복 조회에 대응했다. 단, Report가 새롭다는 사실과 새로운 발생지가 생겼다는 사실은
동일하지 않다. 이 구분은 나중의 신규 발생 건수 알림 설계에도 이어졌다.

초기 빈 DB에서는 과거 Report도 전부 신규처럼 보였다. 기준 데이터 적재와 운영 모니터링을
분리해 과거 데이터를 준비하고, 이후 새로운 Report를 알리는 방식으로 설계했다.
현재 BSE 과거 적재는 알림을 억제하도록 별도로 구현되어 있다.

이전 기록에서는 운영 DB의 최신 보고서를 삭제한 후 재탐지·재저장·Slack 수신으로
전체 흐름을 검증했다. 이는 당시 수행한 검증 이력이며, 앞으로도 운영 데이터 삭제를
테스트의 기본 방식으로 삼겠다는 뜻은 아니다. 회귀 검증은 모의 DB·알림 테스트를 우선한다.

근거: [기본 저장](../../database/db.py), [최초 적재](../../initial_load.py),
[질병별 과거 적재](../../backfill_disease.py).

## RET-BASE-03 — AWS 구상에서 Actions·Aiven 역할 분리로 바꿨다

**상태: 해결 / 근거: 이전 기록, 2026-09-11 Git 이력.**

PC를 계속 켜놓지 않으려면 실행 환경과 데이터 저장소가 모두 PC에서 독립해야 했다.
처음 AWS 서버를 생각했지만 정기적으로 Python을 실행하는 목적에는 GitHub Actions가
더 간단하다고 판단했다. AWS 서버를 실제 운영에 도입한 것으로 기록하지 않는다.

Actions runner는 개인 PC의 로컬 DB를 안정적인 상시 저장소로 사용할 수 없었다.
따라서 로컬 MariaDB/MySQL에서 Aiven MySQL로 옮겼다. HeidiSQL은 계속 관리 도구로
사용했고 저장소 위치만 달라졌다. 이후 상시 응답이 필요한 Slack Socket Mode 봇은
Railway에서 실행하여 주기 실행과 상시 서비스를 분리했다.

Aiven 연결 과정에서 Python mariadb connector의 `RuntimeError: Failed to create exception`이
발생했다는 이전 기록이 있다. HeidiSQL 접속은 성공하므로 DB 서버 전체 장애와
Python 연결 문제를 분리해 보고 PyMySQL로 전환한 뒤 접속을 확인했다.
드라이버 내부 오류의 정확한 발생 원인을 입증했다기보다 호환 가능한 경로로 해결한 사례다.

근거: [DB 연결](../../database/db.py), [운영 워크플로](../../.github/workflows/wahis-monitor.yml),
[README 배포 구조](../../README.md).

## RET-BASE-04 — 환경별 인증서·설정 실패를 애플리케이션 오류와 분리했다

**상태: 해결, 외부 설정 유지 필요 / 근거: 이전 기록, 2026-10-19 커밋.**

로컬의 Windows CA 파일 경로는 Railway와 Linux runner에 존재하지 않는다.
로컬은 `DB_SSL_CA` 경로를, 클라우드는 `DB_SSL_CA_CONTENT` 내용을 임시 PEM 파일로
만들어 사용하는 방식으로 분리했다. `.env`와 인증서는 Git에 넣지 않고
GitHub Secrets에서 실행 중 파일을 생성하도록 했다.

2026-10-19에는 워크플로에서 CA 경로를 지정하고 DB 설정을 사전 검증하는 변경이
추가됐다. 접속 설정 누락을 수집·조회 로직의 문제로 오인하기 전에 실패 지점을 드러내기 위해서다.
이 방식도 만료된 토큰·잘못된 Secret·외부 서비스 장애를 자동 해결하지는 않는다.

근거: [설정 검증](../../database/check_config.py),
[9e4e6e2](https://github.com/jshdata/wahis-slack-monitor/commit/9e4e6e2),
[64640b2](https://github.com/jshdata/wahis-slack-monitor/commit/64640b2).

## RET-BASE-05 — 예약 실행 실패는 최소 workflow로 문제 계층을 좁혔다

**상태: 완화·우회 운영, 근본 원인 미확정 / 근거: 이전 기록, Git 이력.**

수동 `workflow_dispatch`는 성공하지만 GitHub schedule 실행 기록은 생성되지 않는
문제가 있었다. cron을 10분에서 5분으로 바꾸고 기본 브랜치·활성화·권한을 확인했지만
해결하지 못했다. WAHIS나 DB를 계속 바꾸는 대신 echo와 날짜 출력만 하는
`schedule-test.yml`을 만들어 같은 현상을 확인했다.

그 결과 애플리케이션 실행 이후 오류보다 트리거 단계 문제로 범위를 좁혔다.
그러나 GitHub 내부의 정확한 원인은 확인하지 못했다. 이 상태를 ‘GitHub 장애 원인 해결’로
표현하지 않는다.

정상 동작한 dispatch 경로를 재사용해 cron-job.org가 GitHub REST API로 호출하게 했다.
이전 기록에서는 요청 접수(204), workflow 실행, 예약 시간의 Slack 수신까지 확인했다.
서버·DB·수집 코드를 모두 바꾸지 않고 스케줄 담당 부분만 교체한 이유다.

과거 기록에는 테스트 workflow와 schedule 제거가 남아 있다. 하지만 **현재 YAML에는
schedule과 workflow_dispatch가 모두 존재한다.** 과거 우회 성공과 현재 트리거 구성을
구분해야 한다. 실제 어느 경로가 현재 실행을 일으키는지는 운영 이력 확인이 필요하다.
외부 토큰 유지와 복수 트리거의 중복 실행 가능성도 남는다. YAML의 concurrency는
동시 실행을 조절하지만 트리거 자체를 하나로 만드는 기능은 아니다.

근거: [현재 workflow](../../.github/workflows/wahis-monitor.yml),
[최소 workflow 생성 이력](https://github.com/jshdata/wahis-slack-monitor/commit/16d04e8),
[정리 이력](https://github.com/jshdata/wahis-slack-monitor/commit/42a322b).

## RET-BASE-06 — 저장 성공과 상세 적재 완료를 같은 것으로 보지 않았다

**상태: 해결, 중복 알림·외부 실패 가능성은 남음 / 근거: 이전 기록, 코드.**

Report 기본정보 저장 후 상세 API가 실패하면 다음 수집에서 ‘이미 있는 Report’로
건너뛰면서 상세 발생지가 영구 누락될 수 있었다. `detail_loaded`를 도입하고
미완료 보고서를 신규 탐색 전에 복구하도록 했다.

완료 표시는 실제 필요한 저장 단계가 끝난 뒤에 한다. 2026-10-21에는 발생지별
축종 수집도 이 완료 조건에 포함했다. 재적재 시작 시 0으로 되돌려 도중 실패가
복구 대상에 남도록 했다. 발생지별 저장은 트랜잭션이지만 Report 전체가 하나의
거대한 트랜잭션은 아니며, 부분 완료 후 반복 가능한 복구를 사용한다.

Slack 전송 성공 여부도 별도 기록하고 실패를 복구한다. 전송 성공 직후 DB 기록이
실패하면 다음 실행에서 중복 알림이 생길 수 있다. 외부 전송과 DB 커밋을 하나의
원자적 작업으로 만들지 않았다는 한계를 남긴다.

근거: [운영·복구](../../main.py), [보고서 상세 저장](../../database/detail_db.py),
[48b2779](https://github.com/jshdata/wahis-slack-monitor/commit/48b2779).

## RET-BASE-07 — 시간의 기준과 로컬 실행 환경을 명시했다

**상태: 해결, 환경별 재설정 필요 / 근거: 이전 기록, 최근 대화.**

WAHIS 제출시각은 timezone이 있는 ISO 문자열인데 MySQL DATETIME은 timezone을
자체 보존하지 않는다. 현재 UTC 원본을 UTC 저장 기준으로 다루고 사용자 검색의 KST와
변환하는 규칙을 정했다. 다른 offset 원본까지 무조건 timezone만 제거해도 된다고
일반화해서는 안 된다. 보고일과 실제 발생일도 서로 다른 축이다.

파일을 직접 실행해 프로젝트 루트가 모듈 경로에 잡히지 않았던 문제에는
`python -m ...` 실행을 사용했다는 이전 기록이 있다.
최근에는 `python`이 WindowsApps 실행 별칭으로 연결돼 실행되지 않았다.
실제 Anaconda 실행 파일에서 Python 3.12.7 동작을 확인했고, PATH 앞에 실제 경로를
두어 사용자 터미널의 실행 성공을 확인했다. 터미널에서 임시 수정한 PATH와 영구 사용자
PATH 설정을 구분해 안내했다.

근거: [DB 날짜 처리](../../database/db.py), [검색](../../database/query_db.py).
