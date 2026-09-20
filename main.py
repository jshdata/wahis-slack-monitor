import time
import traceback

from wahis.api import get_events
from wahis.detail_api import get_report_detail

from database.db import (
    get_connection,
    get_existing_report_ids,
    insert_disease_report
)

from database.detail_db import (
    save_report_detail
)

from slack.notifier import (
    send_new_report_alert
)


# =========================================================
# 운영 설정
# =========================================================

# 한 페이지에서 가져올 Report 수
PAGE_SIZE = 10

# WAHIS 신규 Report 탐색 최대 페이지 수
MAX_PAGES = 20


# ---------------------------------------------------------
# 상세정보 API 재시도 설정
# ---------------------------------------------------------

# 상세정보 최대 시도 횟수
DETAIL_MAX_RETRIES = 5

# 재시도 기본 대기시간
#
# 1차 실패 → 5초
# 2차 실패 → 10초
# 3차 실패 → 15초
# 4차 실패 → 20초
DETAIL_RETRY_DELAY = 5


# ---------------------------------------------------------
# 미처리 상세정보 자동 복구 설정
# ---------------------------------------------------------

# 한 번의 main.py 실행에서 복구할 최대 Report 수
#
# GitHub Actions가 10분마다 실행되므로
# 한 번에 너무 많은 과거 실패 건을 처리하지 않는다.
RECOVERY_LIMIT = 10


def get_unprocessed_report_ids(
    limit=RECOVERY_LIMIT
):
    """
    detail_loaded = 0인 Report를 조회한다.

    최신 Report부터 최대 limit건을 조회한다.

    이 함수는 조회만 수행하며
    DB 데이터를 수정하지 않는다.
    """

    conn = None
    cursor = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        sql = """
            SELECT report_id
            FROM disease_reports
            WHERE detail_loaded = 0
            ORDER BY
                submission_date DESC,
                report_id DESC
            LIMIT %s
        """

        cursor.execute(
            sql,
            (limit,)
        )

        results = cursor.fetchall()

        return [
            row[0]
            for row in results
        ]

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


def load_report_detail(
    report_id
):
    """
    Report 상세정보를 WAHIS에서 조회하여
    DB에 저장한다.

    성공:
        save_report_detail()에서
        detail_loaded = 1로 변경된다.

    실패:
        detail_loaded = 0 상태로 남는다.

    상세정보 적재 실패가 전체 프로그램을
    중단시키지 않도록 True / False를 반환한다.
    """

    for attempt in range(
        1,
        DETAIL_MAX_RETRIES + 1
    ):

        try:

            print(
                f"상세정보 API 요청: "
                f"report_id={report_id} "
                f"({attempt}/"
                f"{DETAIL_MAX_RETRIES})"
            )

            # ---------------------------------------------
            # WAHIS 상세 API 조회
            # ---------------------------------------------

            detail = get_report_detail(
                report_id
            )

            # ---------------------------------------------
            # 상세정보 DB 저장
            #
            # disease_reports 상세 필드 업데이트
            # outbreaks 저장 / 업데이트
            # report_quantitative 저장
            # detail_loaded = 1
            # ---------------------------------------------

            save_report_detail(
                detail
            )

            print(
                f"상세정보 적재 성공: "
                f"report_id={report_id}"
            )

            return True

        except Exception as e:

            print()

            print(
                "=" * 60
            )

            print(
                "상세정보 적재 오류"
            )

            print(
                "=" * 60
            )

            print(
                f"report_id: "
                f"{report_id}"
            )

            print(
                f"시도: "
                f"{attempt}/"
                f"{DETAIL_MAX_RETRIES}"
            )

            print(
                f"예외 종류: "
                f"{type(e).__name__}"
            )

            print(
                f"오류 내용: "
                f"{repr(e)}"
            )

            print()

            traceback.print_exc()

            print()

            # ---------------------------------------------
            # 최대 재시도 횟수 도달
            # ---------------------------------------------

            if (
                attempt
                >= DETAIL_MAX_RETRIES
            ):

                print(
                    "상세정보 최대 재시도 "
                    "횟수에 도달했습니다."
                )

                print(
                    f"report_id={report_id}는 "
                    "detail_loaded=0 상태로 "
                    "유지됩니다."
                )

                return False

            # ---------------------------------------------
            # 재시도 대기
            # ---------------------------------------------

            wait_seconds = (
                DETAIL_RETRY_DELAY
                * attempt
            )

            print(
                f"{wait_seconds}초 후 "
                "재시도합니다."
            )

            time.sleep(
                wait_seconds
            )

    return False


def recover_unprocessed_details():
    """
    이전 실행에서 상세정보 적재에 실패하여
    detail_loaded = 0으로 남은 Report를 복구한다.

    복구 Report에는 Slack 알림을 발송하지 않는다.

    반환값:
        (복구 성공 건수, 복구 실패 건수)
    """

    print()

    print(
        "=" * 50
    )

    print(
        "미처리 상세정보 복구 확인"
    )

    print(
        "=" * 50
    )

    report_ids = (
        get_unprocessed_report_ids()
    )

    if not report_ids:

        print(
            "복구할 미처리 Report가 "
            "없습니다."
        )

        return 0, 0

    print(
        f"복구 대상: "
        f"{len(report_ids)}건"
    )

    recovery_success = 0
    recovery_fail = 0

    for index, report_id in enumerate(
        report_ids,
        start=1
    ):

        print()

        print(
            "-" * 50
        )

        print(
            f"[복구 "
            f"{index}/"
            f"{len(report_ids)}] "
            f"report_id={report_id}"
        )

        print(
            "-" * 50
        )

        success = load_report_detail(
            report_id
        )

        if success:

            recovery_success += 1

        else:

            recovery_fail += 1

        # WAHIS API에 연속 요청하지 않도록
        # 다음 Report 전에 잠시 대기
        if (
            index
            < len(report_ids)
        ):

            time.sleep(1)

    print()

    print(
        "미처리 상세정보 복구 완료"
    )

    print(
        f"복구 성공: "
        f"{recovery_success}건"
    )

    print(
        f"복구 실패: "
        f"{recovery_fail}건"
    )

    return (
        recovery_success,
        recovery_fail
    )


def main():

    print(
        "=" * 50
    )

    print(
        "WAHIS 신규 리포트 확인 시작"
    )

    print(
        "=" * 50
    )

    # =====================================================
    # 1. 이전 상세정보 실패 건 자동 복구
    # =====================================================

    (
        recovery_success_count,
        recovery_fail_count
    ) = recover_unprocessed_details()

    # =====================================================
    # 2. 신규 Report 탐색
    # =====================================================

    page_number = 0

    total_checked = 0

    new_events = []

    detail_success_count = 0
    detail_fail_count = 0

    slack_success_count = 0
    slack_fail_count = 0

    while (
        page_number
        < MAX_PAGES
    ):

        print()

        print(
            f"{page_number + 1} "
            "페이지 확인 중..."
        )

        # -------------------------------------------------
        # WAHIS에서 한 페이지 조회
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
                "더 이상 조회할 "
                "리포트가 없습니다."
            )

            break

        total_checked += len(
            events
        )

        print(
            f"→ {len(events)}건 수집"
        )

        # -------------------------------------------------
        # 현재 페이지 report_id 추출
        # -------------------------------------------------

        report_ids = [
            event["reportId"]
            for event in events
        ]

        # -------------------------------------------------
        # DB에 이미 존재하는 Report 확인
        # -------------------------------------------------

        existing_ids = (
            get_existing_report_ids(
                report_ids
            )
        )

        # -------------------------------------------------
        # 신규 Report 추출
        # -------------------------------------------------

        page_new_events = [
            event
            for event in events
            if (
                event["reportId"]
                not in existing_ids
            )
        ]

        existing_count = (
            len(events)
            - len(page_new_events)
        )

        print(
            f"기존 리포트: "
            f"{existing_count}건"
        )

        print(
            f"신규 리포트: "
            f"{len(page_new_events)}건"
        )

        # -------------------------------------------------
        # 현재 페이지가 전부 기존 데이터라면 종료
        # -------------------------------------------------

        if not page_new_events:

            print()

            print(
                "현재 페이지의 모든 "
                "리포트가 이미 DB에 "
                "존재합니다."
            )

            print(
                "이전 데이터 조회를 "
                "종료합니다."
            )

            break

        # -------------------------------------------------
        # 신규 Report 처리
        # -------------------------------------------------

        for event in (
            page_new_events
        ):

            report_id = (
                event["reportId"]
            )

            print()

            print(
                "-" * 50
            )

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

            print(
                "-" * 50
            )

            # =============================================
            # 2-1. 기본정보 저장
            # =============================================

            insert_disease_report(
                event
            )

            print(
                f"기본정보 저장 완료: "
                f"report_id={report_id}"
            )

            # =============================================
            # 2-2. 상세정보 저장
            # =============================================

            detail_success = (
                load_report_detail(
                    report_id
                )
            )

            if detail_success:

                detail_success_count += 1

            else:

                detail_fail_count += 1

            # =============================================
            # 2-3. Slack 알림
            #
            # 상세정보 적재 성공 여부와 관계없이
            # 신규 Report 알림은 발송한다.
            # =============================================

            try:

                send_new_report_alert(
                    event
                )

                slack_success_count += 1

                print(
                    f"Slack 알림 성공: "
                    f"report_id={report_id}"
                )

            except Exception as e:

                slack_fail_count += 1

                print()

                print(
                    "Slack 알림 오류"
                )

                print(
                    f"report_id: "
                    f"{report_id}"
                )

                print(
                    f"예외 종류: "
                    f"{type(e).__name__}"
                )

                print(
                    f"오류 내용: "
                    f"{repr(e)}"
                )

                traceback.print_exc()

                print(
                    "Slack 알림 실패와 "
                    "관계없이 다음 Report를 "
                    "계속 처리합니다."
                )

            new_events.append(
                event
            )

        # -------------------------------------------------
        # 다음 페이지
        # -------------------------------------------------

        page_number += 1

    else:

        print()

        print(
            f"안전장치 "
            f"MAX_PAGES="
            f"{MAX_PAGES}에 "
            "도달했습니다."
        )

    # =====================================================
    # 최종 결과
    # =====================================================

    print()

    print(
        "=" * 50
    )

    print(
        "WAHIS 신규 리포트 확인 완료"
    )

    print(
        "=" * 50
    )

    print(
        f"전체 확인: "
        f"{total_checked}건"
    )

    print(
        f"신규 리포트: "
        f"{len(new_events)}건"
    )

    print()

    print(
        f"신규 상세정보 적재 성공: "
        f"{detail_success_count}건"
    )

    print(
        f"신규 상세정보 적재 실패: "
        f"{detail_fail_count}건"
    )

    print()

    print(
        f"미처리 상세정보 복구 성공: "
        f"{recovery_success_count}건"
    )

    print(
        f"미처리 상세정보 복구 실패: "
        f"{recovery_fail_count}건"
    )

    print()

    print(
        f"Slack 알림 성공: "
        f"{slack_success_count}건"
    )

    print(
        f"Slack 알림 실패: "
        f"{slack_fail_count}건"
    )


if __name__ == "__main__":
    main()