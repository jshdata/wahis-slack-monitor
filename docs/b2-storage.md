# Backblaze B2 저장소 이전

비공개 버킷과 해당 버킷으로 제한한 Read and Write Application Key를 사용합니다.
로컬 `.env`와 Render Environment, PDF 수집 GitHub Actions의 `SLACK_MONITOR_ENV`
Secret에 다음 설정을 반영합니다. 키는 채팅·Git 저장소에 올리지 않습니다.

```dotenv
WOAH_PDF_STORAGE=b2
B2_ENDPOINT_URL=https://s3.us-east-005.backblazeb2.com
B2_REGION=us-east-005
B2_BUCKET=wahis-storage-jshdata
B2_ACCESS_KEY_ID=발급받은_keyID
B2_SECRET_ACCESS_KEY=발급받은_applicationKey
STATS_REPORT_BASE_URL=https://wahis-slack-monitor.onrender.com
WEEKLY_REPORT_BASE_URL=https://wahis-slack-monitor.onrender.com
```

기존 DB·Slack 설정은 유지합니다. `WOAH_PDF_STORAGE`는 중복 추가하지 않고 변경합니다.
`keyID`가 Access Key ID, `applicationKey`가 Secret Access Key입니다.
이전 Railway용 `S3_*` 설정은 B2 모드에서 사용하지 않습니다.

## 원본 복구

의존성 설치: `python -m pip install -r requirements.txt`.
PDF 백업 검증: `python -m woah.restore_pdf_backup data/pdf_db_backup/20261019T050327Z`.
같은 명령에 `--upload`를 붙이면 업로드 후 재다운로드 검증합니다.
DB와 로컬 백업을 수정하지 않습니다. 반복 업로드는 버전 보존 정책에 따라 저장량이 늘 수 있습니다.

방역조치 복구: `python -m wahis.upload_control_snapshots`.
각 파일을 재다운로드 검증한 뒤 마지막에 manifest를 게시합니다.

2026-10-28 KST에 PDF 59개와 방역조치 gzip 6개·manifest의 B2 업로드 및
재다운로드 검증을 완료했습니다. 재업로드할 필요 없이 운영 설정 전환을 진행합니다.

## 운영 전환

1. B2 지원 코드와 주간 보고서 URL 변경을 GitHub에 반영하고 Render에 배포합니다.
2. Render Environment에 위 설정을 반영합니다. 지원 코드 배포 이전에
   `WOAH_PDF_STORAGE=b2`를 설정하면 구버전 코드가 실패할 수 있습니다.
3. GitHub Repository Settings → Secrets and variables → Actions에서
   `SLACK_MONITOR_ENV`의 기존 전체 내용 중 저장소·공개 URL 설정을 갱신합니다.
   기존 DB·Slack 설정을 빠뜨리지 않습니다. Secret은 저장 후 원문을 읽을 수 없으므로
   안전하게 보관 중인 전체 설정을 기준으로 편집합니다.
4. `/health` 응답과 Slack PDF 다운로드·방역조치 조회·HTML 표 링크를 확인합니다.
   `/health`의 성공만으로 DB·Slack·B2 정상 동작을 보장하지 않습니다.
5. 새 주간 보고서 링크가 Render 주소를 사용하는지 확인합니다. 과거 발송한
   Railway 링크는 자동으로 바뀌지 않습니다.

공식 연결 안내: https://www.backblaze.com/docs/en/cloud-storage-use-the-aws-sdk-for-python-with-backblaze-b2
