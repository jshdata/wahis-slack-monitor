# WOAH PDF를 Cloudflare R2로 이전

## 버킷 생성

1. Cloudflare 계정에 로그인하고 **R2 Object Storage**를 활성화합니다.
   결제 정보 등록이 요구될 수 있습니다. 무료 제공량 초과 시 과금됩니다.
2. **Create bucket**에서 고유한 이름(예: `wahis-woah-pdfs`)을 지정하고
   **Standard** 저장 클래스를 선택합니다. 공개 접근은 활성화하지 않습니다.
3. R2의 **Manage R2 API Tokens**에서 해당 버킷에만 적용되는
   **Object Read & Write** 권한의 API 토큰을 생성합니다.
4. 표시된 S3 API endpoint, Access Key ID, Secret Access Key를 안전하게 보관합니다.
   Cloudflare 일반 API 토큰이 아니라 S3용 키 쌍을 사용합니다.

공식 안내: https://developers.cloudflare.com/r2/get-started/s3/
요금: https://developers.cloudflare.com/r2/pricing/

## 환경변수

로컬 `.env`와 Railway, PDF 수집 GitHub Actions 등 모든 실행 환경에 설정합니다.
비밀 키는 채팅이나 Git 저장소에 올리지 않습니다.

```dotenv
WOAH_PDF_STORAGE=r2
R2_ENDPOINT_URL=https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com
R2_BUCKET=wahis-woah-pdfs
R2_ACCESS_KEY_ID=YOUR_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY=YOUR_SECRET_ACCESS_KEY
```

`WOAH_PDF_STORAGE`의 기본값은 `mysql`입니다. R2 활성화 시 업로드 실패를
DB 저장으로 숨기지 않고 오류로 처리합니다. 기존 DB 원본은 계속 읽을 수 있습니다.
R2 버킷, 엔드포인트, 객체 경로는 이전 후에도 유지해야 합니다.

## 배포 및 이전

1. `python -m pip install -r requirements.txt`
2. 모든 조회·수집 실행 환경에 새 코드와 환경변수를 배포합니다.
3. `python -m woah.migrate_pdfs`로 기존 PDF를 업로드합니다.
   모든 버전을 하나씩 읽고 SHA-256을 검사한 뒤 업로드하고, 다시 내려받아 검증합니다.
   기본 실행은 DB 원본을 그대로 보관하며 반복 실행할 수 있습니다.
4. Slack의 문서 조회와 PDF 내보내기, 새 문서 수집이 정상인지 확인합니다.
5. 모든 환경이 준비된 뒤에만 `python -m woah.migrate_pdfs --remove-db-copies`를 실행합니다.
   각 파일의 R2 검증 성공 후 해당 DB 원본을 비웁니다. 중단 후 다시 실행할 수 있습니다.
6. Aiven 디스크 여유 공간과 작업 영향을 확인한 뒤 별도로 테이블 재구성을 검토합니다.
   이전 도구는 `OPTIMIZE TABLE`을 실행하지 않습니다.

PDF 객체 키는 `woah/pdf/<sha256>.pdf`입니다. DB의 빈 `pdf_data`와 `sha256` 조합이
이 객체를 가리킵니다. 문서 메타데이터와 추출 텍스트는 DB에 남습니다.
DB 복사본 제거 이후에는 구버전 코드로 돌아가면 PDF 내보내기가 작동하지 않습니다.
R2 객체를 삭제하는 수명 주기 규칙은 설정하지 마세요. DB 백업과 별개로 R2 파일도 보존해야 합니다.
