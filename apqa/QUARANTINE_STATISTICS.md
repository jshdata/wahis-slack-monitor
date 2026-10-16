# 동축산물 월별 검역통계

`quarantine_statistics.py`는 공개 통계의 No2(수출입현황)와 No4(불합격수입현황)를
동일 시작·종료월로 조회합니다. No2는 통계분류 1·2·3·4, No4는 3·4를 각각 조회하며
국가·품목·품명은 전체입니다. 월별 요청은 6개입니다.

```powershell
.\.venv\Scripts\python.exe -m apqa.quarantine_statistics --start 2026-01 --end 2026-09 --load
```

`--load` 없이 실행하면 다운로드와 원본 검증만 수행합니다. 원본과 manifest는
`data/qia_statistics/시작월_종료월/`에 저장합니다. 기존 다운로드가 있으면 재사용합니다.
최신 수정 자료를 다시 받으려면 해당 원본을 별도로 보관한 후 캐시를 교체해야 합니다.

프로젝트의 기존 `database.db.get_connection()`으로 Aiven MySQL에 연결합니다.

| 테이블 | 내용 |
|---|---|
| `qia_trade_statistics` | No2 상세행 |
| `qia_rejection_statistics` | No4 불합격사유별 상세행 |
| `qia_statistics_summaries` | 원본의 소계·총계, 상세행과 별도 |
| `qia_statistics_collections` | 월·통계분류·요청 조건·원본 해시·검증 결과 |

`reference_month`는 해당 월 1일인 DATE이며 일별 실적을 의미하지 않습니다.
`statistics_type`은 1 수출동물, 2 수출축산물, 3 수입동물, 4 수입축산물입니다.
`quantity`는 원본 표시값을 DECIMAL로 저장하고 `unit`은 마리·군·kg·ea로 구분합니다.
수집 시각은 UTC입니다. 빈 품목명·품명은 빈 문자열 그대로 보존합니다.
품목명 공백 등으로 표시 이름이 같은 행이 여러 번 나올 수 있으므로 원본 행 번호를
레코드 키에 포함합니다. 이름만으로 중복 제거하거나 원본 상세행을 합치지 않습니다.

단위별 상세 건수는 원본 총계와 정확히 일치해야 합니다. 중량은 상세행과 총계가
각각 소수점 한 자리로 표시되므로 반올림 허용 범위와 실제 차이를 함께 기록합니다.
상세행의 단위는 원본 품명 표기와 동물/축산물 분류로 판별하며 단위별 총계로 검증합니다.
월·통계분류·자료종류별 데이터를 최대 72개 묶음(12개월)씩 트랜잭션으로 저장하며,
재실행 시 요청한 스냅샷만 교체합니다. 다른 기간의 기존 자료는 유지합니다.
저장 후 모든 상세행·집계행을 다시 읽어 원본 해석값과 비교하며 `verification.json`에
결과를 기록합니다. 기존 질병·검역제한 테이블은 수정하지 않습니다.

원본 엑셀은 `.xls` 확장자의 HTML입니다. 병합 셀과 누락된 닫기 태그를 처리해야 합니다.
No4는 품명 전체일 때 품목 필터가 적용되지 않는 현상을 관찰했으므로 월별 전체를 수집합니다.
통계는 잠정치로 추후 수정될 수 있습니다. 이 모듈은 예약 실행이나 Slack 전송을 하지 않습니다.

검증 테스트:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_quarantine_statistics -v
```
