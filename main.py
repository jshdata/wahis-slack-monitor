from wahis.api import get_events

from database.db import (
    get_existing_report_ids,
    insert_disease_report
)

from slack.notifier import send_new_report_alert


# ---------------------------------------------------------
# 운영 설정
# ---------------------------------------------------------

# 한 페이지에서 가져올 report 수
PAGE_SIZE = 10

# 안전장치:
# 예상치 못한 상황에서 WAHIS 전체 페이지를
# 무한정 조회하지 않도록 최대 페이지 수 제한
MAX_PAGES = 20


def main():

    print("=" * 50)
    print("WAHIS 신규 리포트 확인 시작")
    print("=" * 50)

    page_number = 0

    total_checked = 0
    new_events = []

    while page_number < MAX_PAGES:

        print()
        print(
            f"{page_number + 1} 페이지 확인 중..."
        )

        # -------------------------------------------------
        # 1. WAHIS에서 한 페이지 조회
        # -------------------------------------------------

        data = get_events(
            page_number=page_number,
            page_size=PAGE_SIZE
        )

        events = data.get(
            "list",
            []
        )

        # 데이터가 없으면 종료
        if not events:

            print(
                "더 이상 조회할 리포트가 없습니다."
            )

            break

        total_checked += len(events)

        print(
            f"→ {len(events)}건 수집"
        )

        # -------------------------------------------------
        # 2. 현재 페이지 report_id 추출
        # -------------------------------------------------

        report_ids = [
            event["reportId"]
            for event in events
        ]

        # -------------------------------------------------
        # 3. Aiven에서 한 번에 기존 report 확인
        # -------------------------------------------------

        existing_ids = get_existing_report_ids(
            report_ids
        )

        # -------------------------------------------------
        # 4. 신규 report 추출
        # -------------------------------------------------

        page_new_events = [
            event
            for event in events
            if event["reportId"] not in existing_ids
        ]

        existing_count = (
            len(events)
            - len(page_new_events)
        )

        print(
            f"기존 리포트: {existing_count}건"
        )

        print(
            f"신규 리포트: {len(page_new_events)}건"
        )

        # -------------------------------------------------
        # 5. 현재 페이지가 전부 기존 데이터라면 종료
        # -------------------------------------------------

        if not page_new_events:

            print()
            print(
                "현재 페이지의 모든 리포트가 "
                "이미 DB에 존재합니다."
            )

            print(
                "이전 데이터 조회를 종료합니다."
            )

            break

        # -------------------------------------------------
        # 6. 신규 report 처리
        # -------------------------------------------------

        for event in page_new_events:

            report_id = event["reportId"]

            print()
            print(
                f"신규 리포트 발견: "
                f"report_id={report_id}"
            )

            print(
                f"국가: "
                f"{event.get('country')}"
            )

            print(
                f"질병: "
                f"{event.get('disease')}"
            )

            # DB 저장
            insert_disease_report(
                event
            )

            # Slack 알림
            send_new_report_alert(
                event
            )

            new_events.append(
                event
            )

        # -------------------------------------------------
        # 7. 다음 페이지
        # -------------------------------------------------

        page_number += 1

    else:

        print()
        print(
            f"안전장치 MAX_PAGES="
            f"{MAX_PAGES}에 도달했습니다."
        )

    # -----------------------------------------------------
    # 최종 결과
    # -----------------------------------------------------

    print()
    print("=" * 50)
    print("WAHIS 신규 리포트 확인 완료")
    print("=" * 50)

    print(
        f"전체 확인: "
        f"{total_checked}건"
    )

    print(
        f"신규 리포트: "
        f"{len(new_events)}건"
    )


if __name__ == "__main__":
    main()