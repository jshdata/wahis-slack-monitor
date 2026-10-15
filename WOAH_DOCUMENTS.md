# WOAH 자체 청정 선언 PDF와 ChatGPT 요약

ASF·HPAI·FMD·LSD의 공개 선언 목록과 PDF 원본을 기존 MySQL에 보관합니다.
요약은 사용자가 ChatGPT에 PDF를 직접 첨부하는 방식입니다. API 키나 API 결제가 필요하지 않습니다.
ChatGPT 계정의 파일 업로드·사용 한도는 적용됩니다.

## 사용 방법

1. Slack에서 `/wahis-stats` → **WOAH 자체 청정 선언 PDF 보기**를 선택합니다.
2. 원하는 문서의 **ChatGPT로 요약하기**를 누릅니다.
3. **원문 PDF**를 열어 파일을 내려받습니다.
4. **ChatGPT 열기**를 누르고 내려받은 PDF를 직접 첨부합니다.
5. Slack에 표시된 요청문을 복사해 ChatGPT에 함께 보냅니다.

Slack–GPT API 연동은 필요하지 않습니다. PDF와 요청문은 자동 전송되지 않습니다.
요약 결과는 ChatGPT에서 확인하며 Slack이나 DB에 자동 저장되지 않습니다.
국가 자체 청정 선언은 WOAH 공식 인정과 구분해야 하며, 원문 근거 페이지를 확인하세요.

## 설치 및 실행

기존 `.env`의 DB·Slack 설정을 그대로 사용합니다. API 키와 모델 설정은 사용하지 않습니다.
Windows에서는 프로젝트 폴더의 PowerShell에서 실행합니다.

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
& '.\.venv\Scripts\python.exe' woah_main.py
& '.\.venv\Scripts\python.exe' -m slack.query_app
```

Windows 수집기는 설치된 Microsoft Edge를 비표시 모드로 사용합니다.
Linux에서 수집하려면 Chromium과 OS 의존성을 설치합니다. Slack 조회에는 브라우저가 필요하지 않습니다.

```sh
python -m pip install -r requirements.txt
python -m playwright install --with-deps chromium
python woah_main.py
python -m slack.query_app
```

기존 `/wahis-stats`의 PDF 보기 버튼은 별도 Slack 명령 등록 없이 사용할 수 있습니다.
별도 명령을 원하면 기존 Slack 앱의 Slash Commands에 `/woah-docs`를 추가합니다.
기존 Socket Mode 설정을 유지하고, Slack이 요구하는 경우 앱 설정 변경을 적용합니다.

## 수집 및 내보내기

```powershell
# DB 접속 없이 공개 목록 확인
& '.\.venv\Scripts\python.exe' woah_main.py --discover-only
# 일부 질병만 수집
& '.\.venv\Scripts\python.exe' woah_main.py --disease ASF HPAI
# 실패한 PDF만 재시도
& '.\.venv\Scripts\python.exe' woah_main.py --retry-failed
# DB에 저장된 원본 PDF와 ChatGPT용 요청문을 PC에 저장
& '.\.venv\Scripts\python.exe' woah_main.py --export-id 20
# 출력 폴더 지정
& '.\.venv\Scripts\python.exe' woah_main.py --export-id 20 --output-dir woah_exports
```

내보낸 파일은 기본적으로 `woah_exports`에 저장하며 Git에서 제외합니다.
원문 링크가 사라져도 저장된 원본은 이 명령으로 내보낼 수 있습니다.
동일 경로에 다른 내용의 파일이 있으면 덮어쓰지 않고 오류를 표시합니다.

일반 수집은 같은 URL의 PDF 교체도 확인합니다. `--retry-failed`는 READY인 문서를 생략합니다.
GitHub Actions의 **WOAH PDF Monitor**가 매일 한국시간 오전 9시에 전체 수집을 실행합니다.
오전 10시에는 실패·미실행 여부를 확인해 필요한 질병만 재시도합니다.
일부 PDF 실패는 실패 항목만 다시 받고, 전체 목록 조회 실패나 당일 미실행은 전체 확인을 다시 합니다.
정상 완료한 질병은 오전 10시 작업에서 건너뜁니다.

기존 GitHub Secrets `SLACK_MONITOR_ENV`와 `DB_SSL_CA_CERT`를 재사용합니다.
추가 API 키나 PC 상시 실행은 필요하지 않습니다. GitHub 예약 실행은 부하에 따라 지연될 수 있습니다.
Actions → **WOAH PDF Monitor** → **Run workflow**에서 수동 실행도 가능합니다.

## DB 저장

| 테이블 | 내용 |
| --- | --- |
| `woah_documents` | 질병·국가·게시일·적용 범위, 원문 URL, 다운로드 상태 |
| `woah_document_versions` | PDF `LONGBLOB`, SHA-256, 크기, 페이지 수, 페이지별 본문 JSON |
| `woah_collection_runs` | 질병별 수집 결과와 발견·저장·실패 건수 |

미사용 `woah_document_summaries` 테이블은 데이터 0건 및 참조 없음 확인 후 삭제했습니다.
원본 PDF·버전·수집 이력 테이블은 유지합니다.
같은 PDF는 기존 버전을 재사용하고 교체된 PDF는 이전 버전도 보관합니다.
수집 실패나 목록에서 문서가 사라진 경우 기존 자료를 삭제하지 않습니다.

파일 크기 한도는 20MB이며 MySQL `max_allowed_packet`에는 SQL 이스케이프를 고려한 여유가 필요합니다.
스캔본은 본문이 비어도 원본을 보관하고 `IMAGE_ONLY`로 기록합니다.

## 수집 상태

- `NO_DOCUMENTS`: 전체 목록을 정상 확인했으나 해당 질병의 문서가 없음
- `NO_PDF_LINK`: 목록 행은 있지만 PDF 링크가 없음
- `DOWNLOAD_FAILED`: 다운로드 또는 PDF 파싱 실패
- `COLLECTION_FAILED`: 목록 자체를 확인하지 못함
- `PARTIAL`: 일부 문서 실패. `--retry-failed`로 재시도 가능

문서가 없다는 사실을 질병 부재나 수입 허용으로 해석하지 않습니다.
목록에서 사라진 문서를 자동으로 선언 취소로 판단하지 않습니다.
Power BI 형식 변경 또는 전체 목록 수집 여부를 확인할 수 없는 경우에는 수집 실패로 기록합니다.
보고서 주소가 교체되면 `WOAH_REPORT_URL` 환경변수로 지정할 수 있습니다.

## 검증

PDF 보기에서 질병(또는 모든 질병), 시작 날짜, 종료 날짜를 선택하고
**권역별 선언 국가 표**를 누르면 각 질병에 대해 모든 권역의 선언 국가를 중복 없이 표시합니다.
날짜 기본값은 전체이며, **전체 기간으로 초기화**로 날짜 조건을 해제합니다.
기간은 WOAH 게시일 기준(양 끝 날짜 포함)이며 한쪽 날짜만 지정할 수도 있습니다.
기간을 지정하면 게시일 미상 문서는 제외하고 건수를 안내합니다.
표는 아시아·유럽·아프리카·아메리카·오세아니아·기타 순서이며 북미·남미는 아메리카로 묶습니다.
국가 자체 선언에는 지역·구획 선언도 포함되므로 현재 국가 전체의 청정 상태를 의미하지 않습니다.

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -p 'test_woah*.py' -v
```

단위 테스트는 운영 DB·네트워크·외부 AI 서비스를 호출하지 않습니다.
