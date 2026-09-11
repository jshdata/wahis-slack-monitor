from wahis.api import get_all_events
from database.db import insert_disease_report


def main():

    print("=" * 50)
    print("WAHIS 전체 데이터 초기 적재 시작")
    print("=" * 50)

    events = get_all_events(
        page_size=10
    )

    print()
    print("=" * 50)
    print("Aiven DB 저장 시작")
    print("=" * 50)

    success_count = 0
    fail_count = 0

    for index, event in enumerate(
        events,
        start=1
    ):

        try:

            insert_disease_report(event)

            success_count += 1

        except Exception as e:

            fail_count += 1

            print(
                f"저장 실패 "
                f"[{index}/{len(events)}] "
                f"report_id={event.get('reportId')}"
            )

            print(e)

    print()
    print("=" * 50)
    print("초기 적재 완료")
    print("=" * 50)

    print(f"전체 수집: {len(events)}건")
    print(f"저장 성공: {success_count}건")
    print(f"저장 실패: {fail_count}건")


if __name__ == "__main__":
    main()