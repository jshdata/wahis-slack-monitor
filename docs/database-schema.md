# WAHIS 수집 데이터·DB 데이터 사전

[README](../README.md#수집-데이터와-db-구조) · 문서 확인일: **2026-11-03 (KST)**

현재 저장 코드에 근거한 주요 컬럼·연결 관계 설명입니다. 운영 DB의 실시간 스키마 덤프나
전체 DDL이 아니며, 문서를 읽는 것만으로 테이블이나 컬럼을 생성하지 않습니다.
저장·변경 시 실제 코드는 아래 근거 파일과 대조하세요.

## 1. 수집 범위와 데이터 단위

| 원천 | 저장하는 내용 | 주요 저장 테이블 |
|---|---|---|
| WAHIS 목록 API | 신규 보고 식별·기본정보 | `disease_reports` |
| 보고서 상세 API | 혈청형/아형·사건 상태·발생지 목록·보고서 정량자료 | `disease_reports`, `outbreaks`, `report_quantitative` |
| 발생지 상세 API | 해당 발생지의 축종 ID·이름·야생 여부 | `outbreak_species`, `outbreaks`의 분류·수집 상태 |

- **Event:** 여러 최초·후속 보고서를 묶는 사건입니다. 별도 events 테이블을 뜻하지 않으며
  `disease_reports.event_id`와 `outbreaks.event_id`로 연결합니다.
- **Report:** 보고서 한 건입니다. 후속 보고가 새로 등록돼도 신규 발생지가 없을 수 있습니다.
- **Outbreak:** `outbreak_id`로 구분하는 발생 기록입니다. 고유 지명·농장·좌표 개수와 다릅니다.
- **Species:** 한 발생지에 여러 종이 있을 수 있어 별도 행으로 저장합니다.
- **Quantitative:** 보고서별 축종의 신규/누계 수치입니다. 개별 발생지의 수치라고 대입하지 않습니다.

대상은 HPAI·ASF·FMD·LSD·BSE입니다. HPAI는 가금과 가금 외 질병 코드를 함께 수집하며,
가금/가금 외와 사육/야생 분류는 서로 다른 기준입니다.

## 2. 핵심 테이블

### disease_reports — 보고서

기준 식별자는 `report_id`입니다. 신규 보고 탐지와 Slack·ntfy 알림의 출발점입니다.

| 컬럼 | 의미 |
|---|---|
| `report_id` | 원본 reportId, 보고서 식별자 |
| `event_id` | 보고서가 속한 사건 ID |
| `country`, `disease` | 보고 국가와 WAHIS 질병명 |
| `subtype` | 혈청형·아형 등 세부 분류. 모든 보고에 제공되는 것은 아님 |
| `submission_date` | 보고서 제출 시각 |
| `event_start_date` | 사건 시작일. 개별 발생지 시작일과 구분 |
| `report_number`, `report_type` | 사건 내 보고 차수와 원본 보고 유형 |
| `event_status`, `report_status`, `reason` | 사건·보고 상태와 원본 통보 사유 |
| `is_aquatic`, `is_last_report_unchanged` | 수생동물 관련 여부·직전 보고 대비 동일 여부 |
| `detail_loaded` | 0: 상세 적재 미완료, 1: 필요한 상세 저장 단계 완료 |
| `slack_sent`, `slack_sent_at`, `slack_retry_count` | Slack 전송·복구 상태. 과거 적재에서 알림 제외를 위해 완료 처리한 건도 포함 가능 |
| `slack_event_json` | 알림 생성·재전송용 목록 이벤트 정보. 발생지 상세 전체 JSON이 아님 |

`detail_loaded=1`은 원본 API가 제공하지 않은 필드까지 모두 채워졌다는 뜻이 아닙니다.
ntfy는 `ntfy_outbox`에 독립적인 전송 상태를 저장합니다.

### outbreaks — 발생 기록

기준 식별자는 `outbreak_id`입니다. 동일 ID가 후속 보고에서 수정돼도 새 행으로 늘리지 않습니다.

| 컬럼 | 의미 |
|---|---|
| `outbreak_id`, `event_id` | 발생 기록 ID와 소속 사건 ID |
| `created_by_report_id` | 이 발생지를 처음 등록한 보고서. 신규 발생 건수의 기준 |
| `last_update_report_id` | 현재 저장된 발생지 내용을 마지막으로 갱신한 보고서 |
| `start_date`, `end_date` | 발생 시작일·종료일 |
| `admin_division`, `location` | 행정구역·위치명 |
| `latitude`, `longitude`, `location_approx` | 좌표와 근사 위치 표시 여부 |
| `epi_unit_type`, `cluster_count` | 역학 단위 종류와 집단발생의 구성 단위 수 |
| `oie_reference`, `national_reference` | WAHIS·보고 국가의 참조번호 |
| `description`, `species_number` | 상황 설명과 보고된 동물종 수 |
| `animal_category` | `domestic` / `wild` / `mixed` / `unknown` |
| `species_loaded_report_id` | 축종 수집이 완료된 기준 보고서 ID |
| `species_loaded_at` | 축종 수집 완료 시각(UTC) |

`species_loaded_report_id`가 `COALESCE(last_update_report_id, created_by_report_id)`와 같으면
현재 저장된 발생지 버전까지 축종 적재를 완료한 상태입니다. 다르면 갱신 대기일 수 있습니다.
최초·최신 보고 관계만 보관하므로 중간의 모든 수정 보고와 그 당시 원본을 복원할 수는 없습니다.

### outbreak_species — 발생지별 축종

현재 생성 코드의 기본키는 **`(outbreak_id, row_index)`**입니다.
`row_index`는 수집된 목록 내 행 번호이며 독립된 동물종 ID가 아닙니다.

| 컬럼 | 의미 |
|---|---|
| `outbreak_id` | 연결할 발생 기록 ID |
| `row_index` | 해당 발생지의 축종 목록 내 행 번호 |
| `report_id` | 이 축종 자료를 수집한 기준 보고서 ID |
| `species_id` | 원본 동물종 ID |
| `species_name` | 원본 동물종 이름. 예: Birds, Cattle, Wild boar |
| `is_wild` | 1: 야생, 0: 사육, NULL: 미확인 |

재수집 시 해당 발생지의 축종 행을 교체하고 분류·완료 표시를 함께 커밋합니다.
따라서 이 테이블은 과거 버전 전체 이력 테이블이 아닙니다.

발생지 분류 규칙:

| 확인 결과 | `animal_category` |
|---|---|
| 모든 항목이 사육 | `domestic` |
| 모든 항목이 야생 | `wild` |
| 사육과 야생이 모두 확인됨 | `mixed` |
| 빈 목록, 또는 일부 미확인이고 혼합 여부를 확정할 수 없음 | `unknown` |

사육과 야생이 둘 다 확인되면 미확인 항목이 추가로 있어도 `mixed`입니다.
종 이름의 wild/domestic 포함 여부로 추정하지 않습니다.

### report_quantitative — 보고서별 정량자료

보고서·자료 구분·원본 정량 ID와 축종을 기준으로 읽습니다.

| 컬럼 | 의미 |
|---|---|
| `report_id` | 연결 보고서 ID |
| `data_type` | `new`: 이번 보고 신규 수치, `total`: 해당 보고 시점 누계 |
| `outbreak_quantities_id` | 원본 정량자료 ID. **outbreak_id와 다른 식별자** |
| `species_id`, `species_name`, `is_wild` | 보고서 정량자료의 축종·야생 여부. 발생지별 분류를 대신하지 않음 |
| `susceptible`, `cases`, `deaths` | 감수성·감염/발병·폐사 수치 |
| `killed`, `slaughtered`, `vaccinated` | 살처분·도축·예방접종 수치 |
| `unit` | 원본 수량 단위. 다른 단위를 무조건 합산하지 않음 |

누계는 후속 보고마다 반복되므로 여러 보고서의 total을 단순 합산하지 않습니다.
`NULL`은 미보고·미확인일 수 있으며 실제 보고된 0과 구분합니다.

## 3. 연결 관계와 조회 시 주의사항

| 연결 | 용도·주의점 |
|---|---|
| `disease_reports.event_id` ↔ `outbreaks.event_id` | 사건별 발생지 조회. 후속 보고 전체를 JOIN하면 발생지 행이 증식할 수 있음 |
| `outbreaks.created_by_report_id` → `disease_reports.report_id` | 해당 보고서가 처음 등록한 발생지 조회 |
| `outbreaks.last_update_report_id` → `disease_reports.report_id` | 현재 보관한 최신 갱신 보고서 조회 |
| `outbreak_species.outbreak_id` → `outbreaks.outbreak_id` | 발생지별 축종. JOIN 후 발생 건수는 DISTINCT로 계산 |
| `report_quantitative.report_id` → `disease_reports.report_id` | 보고서의 정량자료 조회 |

위 표는 코드의 논리적 연결입니다. 모든 연결이 DB의 FOREIGN KEY 제약으로 선언되어 있다는
뜻은 아닙니다. 보고서별 대시보드도 복원 가능한 최초·최신 관계만 사용하며, 과거의
모든 발생지 소속 스냅샷이 있는 것처럼 표시하지 않습니다.

### 읽기 전용 SQL 예시

```sql
-- 한 사건의 고유 발생 기록 수 (집단발생 구성 단위 수·감염 동물 수와 구분)
SELECT COUNT(DISTINCT outbreak_id) AS outbreak_count
FROM outbreaks
WHERE event_id = 7176;

-- 한 보고서의 신규 발생 기록 수: 기존 ID 수정 제외
SELECT COUNT(DISTINCT outbreak_id) AS new_outbreak_count
FROM outbreaks
WHERE created_by_report_id = 186524;

-- 현재 버전까지 축종 적재가 완료된 발생지의 사육/야생 분류
SELECT animal_category, COUNT(DISTINCT outbreak_id) AS outbreak_count
FROM outbreaks
WHERE species_loaded_report_id = COALESCE(last_update_report_id, created_by_report_id)
GROUP BY animal_category;

-- 발생지별 축종 이름과 야생 여부
SELECT outbreak_id, species_id, species_name, is_wild, report_id
FROM outbreak_species
WHERE outbreak_id = 198522
ORDER BY row_index;
```

예시 ID는 공개 WAHIS 자료를 설명하기 위한 값입니다. 결과값은 수집 시점에 따라 달라집니다.
운영 알림에서는 상세 미완료 보고서의 0건을 확정하지 않고 미확인으로 표시합니다.

## 4. 연관 자료의 보관 위치

| 자료 | 저장 위치·관련 문서 |
|---|---|
| 국가별 권역 | `country_regions` — 국가·권역 필터 |
| 동물 개체수 | `wahis_animal_population` — 연례 자료, 질병 보고서의 cases와 구분 |
| APQA 수입 허용·제한·변경 이력 | `apqa_import_permissions`, `apqa_import_restrictions`, `apqa_import_history` |
| QIA 월별 검역통계 | 상세·소계·수집 단위를 분리. [수집 및 검증 문서](../apqa/QUARANTINE_STATISTICS.md) |
| WOAH PDF | DB에 문서 메타데이터·버전 정보, 설정된 비공개 객체 저장소에 PDF. [Railway 안내](railway-pdf-storage.md) |
| 방역조치 스냅샷 | 객체 저장소의 압축 CSV와 조회용 임시 SQLite 캐시. [파일 저장·조회](control-measures-storage.md) |
| 주간 HTML·알림 복구 | `weekly_html_reports`, `ntfy_outbox` 등 운영용 테이블 |

**발생지 상세 전체 JSON과 축종 raw_json은 현재 적재에서 저장하지 않습니다.**
보고서 정량자료·알림 재전송용 이벤트 JSON·PDF 등 다른 자료의 저장 여부와 혼동하지 않습니다.
과거 JSON 저장분 정리 절차는 [축종 적재 안내](outbreak-species-loading.md)를 참고하세요.

## 5. 문서 근거

- [기본정보·DB 연결](../database/db.py), [보고서 상세 저장](../database/detail_db.py)
- [발생지 축종 스키마·저장·분류](../database/outbreak_species_db.py)
- [신규 발생 알림 집계](../database/report_alert_details.py), [발생 통계](../database/stats_db.py)
- [보고서별 지도·추이 조회](../database/report_dashboard_db.py)
- [한글 컬럼 설명](../database/column_comments_ko.json)

공개 문서에는 DB 호스트·계정·비밀번호·인증서 내용·실제 덤프를 넣지 않습니다.
