# Railway PDF 저장소

Railway의 배포된 버킷 Credentials에 표시된 실제 S3 버킷명과 키를 사용합니다.
표시 이름과 실제 버킷명은 다를 수 있습니다. 버킷은 비공개로 유지합니다.

로컬 `.env`, Railway 봇 Variables, PDF를 수집하는 GitHub Actions 등
모든 조회·수집 환경에 다음 변수를 설정합니다. 비밀 키를 Git에 저장하지 않습니다.
현재 GitHub Actions 수집 워크플로는 `SLACK_MONITOR_ENV` Secret 내용을
`.env`로 읽습니다. 이 Secret에도 기존 DB 설정을 유지하며 아래 변수를 추가해야 합니다.

```dotenv
WOAH_PDF_STORAGE=railway
S3_ENDPOINT_URL=https://t3.storageapi.dev
S3_BUCKET=Credentials에 표시된 실제 버킷명
S3_REGION=auto
S3_ACCESS_KEY_ID=Credentials의 Access Key ID
S3_SECRET_ACCESS_KEY=Credentials의 Secret Access Key
```

Endpoint와 Region은 반드시 Credentials에 표시된 값을 사용하세요.
기본 URL 방식은 virtual-hosted입니다. Credentials에서 path-style을 명시한다면
`S3_ADDRESSING_STYLE=path`를 추가합니다.

1. `python -m pip install -r requirements.txt`로 의존성을 설치합니다.
2. `python -m woah.migrate_pdfs`는 DB PDF를 업로드하고 다운로드하여
   SHA-256과 원본 바이트를 검증합니다. DB 원본은 그대로 유지합니다.
3. 새 코드와 같은 저장소 설정을 모든 조회·수집 환경에 배포하고,
   PDF 내보내기와 새 문서 수집이 정상인지 확인합니다.
4. 모든 환경의 동작 확인 후에만 `python -m woah.migrate_pdfs --remove-db-copies`로
   검증된 PDF의 DB 원본을 비웁니다. 자동 테이블 재구성은 하지 않습니다.

객체 위치는 `woah/pdf/<sha256>.pdf`입니다. DB의 빈 pdf_data와 sha256으로
외부 파일을 식별하므로 DB 원본 제거 후에는 구버전 코드로 되돌릴 수 없습니다.
버킷의 파일과 접속 설정을 보존하고 자동 삭제 수명 주기 규칙은 사용하지 마세요.
DB 백업과 별개로 버킷 파일도 보존해야 합니다.

공식 문서: https://docs.railway.com/storage-buckets
요금: https://docs.railway.com/storage-buckets/billing
