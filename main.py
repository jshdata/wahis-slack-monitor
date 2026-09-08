from wahis.api import get_latest_events

from database.db import (
    is_report_exists,
    insert_disease_report
)

from slack.notifier import send_new_report_alert


def main():

    print("=" * 50)
    print("WAHIS 신규 리포트 확인 시작")
    print("=" * 50)

    # 최신 3페이지 조회
    events = get_latest_events(
        page_count=3,
        page_size=10
    )

    print()
    print("=" * 50)
    print("신규 리포트 확인")
    print("=" * 50)
    print()

    new_events = []

    for event in events:

        report_id = event["reportId"]

        # DB에 이미 존재하는지 확인
        if is_report_exists(report_id):

            print(
                f"기존 리포트: "
                f"report_id={report_id}"
            )

        else:

            print(
                f"신규 리포트: "
                f"report_id={report_id}"
            )

            new_events.append(event)

            # DB 저장
            insert_disease_report(event)

            # Slack 알림
            send_new_report_alert(event)

    print()
    print("=" * 50)
    print("신규 리포트 확인 완료")
    print("=" * 50)

    print(
        f"전체 확인: {len(events)}건"
    )

    print(
        f"신규 리포트: {len(new_events)}건"
    )


if __name__ == "__main__":
    main()