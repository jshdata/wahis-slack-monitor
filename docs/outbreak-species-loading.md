# 발생지 축종·사육/야생 적재

신규 보고서 자동 적재(`main.py`)와 과거 보고서 적재(`detail_initial_load.py`,
`backfill_disease.py`)는 공통 `save_report_detail()`에서 발생지 기본정보 저장 후
축종·사육야생 정보까지 수집합니다. 최신 버전의 완료 건은 API 호출을 건너뜁니다.
실패하면 보고서를 미완료로 남겨 기존 보고서 재시도·복구 경로에서 다시 시도합니다.
기존에 완료된 과거 보고서의 누락 축종은 아래 배치 명령으로 계속 적재하세요.

현재 모드는 API JSON을 저장하지 않습니다. `outbreaks`에는 사육·야생·혼합·미확인
분류와 완료 보고서 ID·수집 시각을, `outbreak_species`에는 발생지 ID·행 번호·
보고서 ID·동물종 ID·이름·is_wild만 저장합니다.

```powershell
# 남은 건수
python outbreak_species_load.py --status

# 100건 적재
python outbreak_species_load.py --limit 100

# 한 시간씩 이어서 적재
python outbreak_species_load.py --all --max-minutes 60

# 새 DB에서 최초 테이블/컬럼 생성
python outbreak_species_load.py --init-schema --limit 10
```

완료된 발생지는 건너뛰고 실패 건 및 보고서가 갱신된 발생지만 다시 처리합니다.
기존 JSON을 제거해도 완료된 축종·분류를 다시 수집하지 않습니다.
빈 동물종 목록은 unknown으로 완료하며 누락·잘못된 응답은 미완료로 남깁니다.

기본 동시 API 요청은 3개이며 전체 요청 시작 간격은 0.2초입니다.
작업별 DB 연결은 재사용하고 저장은 한 번에 한 건씩 트랜잭션 처리합니다.
`--workers`, `--delay`로 조절할 수 있습니다.
실패 시 총 5회 시도하며 3·6·9·12초 대기합니다.
`--attempts`, `--retry-delay`로 조절합니다.
HTTP 429/503의 Retry-After 값이 더 길면 이를 따릅니다.

건수 제한은 처리 시도 발생지 수입니다. 시간 제한과 Ctrl+C는 진행 중인
묶음의 저장·재시도가 끝난 뒤 종료하므로 시간이 초과될 수 있습니다.
이미 커밋된 건은 유지됩니다. 적재 프로세스는 한 번에 하나만 실행하세요.

## 이전 JSON 저장 방식 정리

모든 적재 프로세스를 종료한 뒤 실행합니다.

```powershell
python cleanup_outbreak_json.py
```

기존 자료를 `data/outbreak_json_backup`에 gzip으로 백업·검증한 뒤
`outbreak_species.raw_json` 컬럼과 `outbreak_detail_snapshots` 테이블만 제거합니다.
동물종·발생지·분류·완료 표시는 유지합니다. 반복 실행할 수 있으며
일반 적재 때마다 실행할 필요는 없습니다.
DDL은 자동 커밋되므로 중간 실패 시 일부 정리는 이미 완료돼 있을 수 있습니다.

JSON 정리 후에도 물리적 디스크 사용량은 즉시 줄지 않을 수 있습니다。
자동 OPTIMIZE TABLE은 실행하지 않습니다.
방역조치·수치 등이 나중에 필요하면 기존 로컬 백업을 활용하거나 API를 다시 조회합니다.

```sql
SELECT animal_category, COUNT(*) AS outbreak_count
FROM outbreaks
WHERE species_loaded_report_id = COALESCE(last_update_report_id, created_by_report_id)
GROUP BY animal_category;
```
