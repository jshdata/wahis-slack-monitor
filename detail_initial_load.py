import time
import traceback

from database.db import get_connection
from database.detail_db import save_report_detail
from wahis.detail_api import get_report_detail


# =========================================================
# 설정
# =========================================================

# Report 한 건 처리 후 대기 시간
REQUEST_DELAY = 1.0

# Report 하나에 대한 최대 재시도 횟수
MAX_RETRIES = 5

# 재시도 기본 대기시간
#
# 1차 실패 → 5초
# 2차 실패 → 10초
# 3차 실패 → 15초
# ...
RETRY_DELAY = 5

# 테스트 시 처리할 최대 Report 수
#
# 오류 확인 중:
# TEST_LIMIT = 3
#
# 배치 적재:
# TEST_LIMIT = 200
# TEST_LIMIT = 500
#
# 전체 적재:
# TEST_LIMIT = None
TEST_LIMIT = 100


def get_unprocessed_report_ids(limit=None):
    """
    아직 상세정보가 적재되지 않은 Report ID를 조회한다.

    submission_date 기준으로
    오래된 Report부터 처리한다.
    """

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        if limit is None:

            sql = """
                SELECT report_id
                FROM disease_reports
                WHERE detail_loaded = 0
                ORDER BY
                    submission_date ASC,
                    report_id ASC
            """

            cursor.execute(sql)

        else:

            sql = """
                SELECT report_id
                FROM disease_reports
                WHERE detail_loaded = 0
                ORDER BY
                    submission_date ASC,
                    report_id ASC
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


def get_remaining_count():
    """
    detail_loaded = 0인 Report 수를 반환한다.
    """

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        sql = """
            SELECT COUNT(*)
            FROM disease_reports
            WHERE detail_loaded = 0
        """

        cursor.execute(sql)

        result = cursor.fetchone()

        return result[0]

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()


def load_report_detail(report_id):
    """
    Report 하나의 상세정보를 조회하고 저장한다.

    실패하면 MAX_RETRIES만큼 재시도한다.

    오류 발생 시:
    - 예외 종류
    - 예외 내용
    - 전체 traceback

    을 출력한다.

    모든 저장이 성공하면
    save_report_detail() 내부에서
    detail_loaded = 1로 변경된다.
    """

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            print(
                "상세 API 요청: "
                f"report_id={report_id}"
            )

            detail = get_report_detail(
                report_id
            )

            save_report_detail(
                detail
            )

            print(
                "처리 성공: "
                f"report_id={report_id}"
            )

            return True

        except Exception as e:

            print()
            print("=" * 60)
            print("상세정보 처리 오류")
            print("=" * 60)

            print(
                f"report_id: {report_id}"
            )

            print(
                f"시도: "
                f"{attempt}/{MAX_RETRIES}"
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
            print(
                "========== TRACEBACK =========="
            )

            traceback.print_exc()

            print(
                "==============================="
            )
            print()

            # ---------------------------------------------
            # 최대 재시도 횟수 도달
            # ---------------------------------------------

            if attempt >= MAX_RETRIES:

                print(
                    "최대 재시도 횟수를 "
                    "초과했습니다."
                )

                print(
                    f"report_id={report_id}는 "
                    "미처리 상태로 유지됩니다."
                )

                return False

            # ---------------------------------------------
            # 재시도 대기
            # ---------------------------------------------

            wait_seconds = (
                RETRY_DELAY * attempt
            )

            print(
                f"{wait_seconds}초 후 "
                "재시도합니다."
            )

            time.sleep(
                wait_seconds
            )

    return False


def main():

    start_time = time.time()

    print("=" * 60)
    print(
        "WAHIS 상세정보 초기 적재 시작"
    )
    print("=" * 60)
    print()

    # -----------------------------------------------------
    # 전체 미처리 건수
    # -----------------------------------------------------

    total_remaining = (
        get_remaining_count()
    )

    print(
        f"전체 미처리 Report: "
        f"{total_remaining}건"
    )

    # -----------------------------------------------------
    # 테스트 / 배치 모드 표시
    # -----------------------------------------------------

    if TEST_LIMIT is None:

        print(
            "전체 적재 모드"
        )

    else:

        print(
            "현재 배치 모드: "
            f"최대 {TEST_LIMIT}건만 처리"
        )

    print()

    # -----------------------------------------------------
    # 처리 대상 조회
    # -----------------------------------------------------

    report_ids = (
        get_unprocessed_report_ids(
            TEST_LIMIT
        )
    )

    target_count = len(
        report_ids
    )

    print(
        f"이번 실행 대상: "
        f"{target_count}건"
    )

    print()

    # -----------------------------------------------------
    # 처리할 데이터가 없는 경우
    # -----------------------------------------------------

    if target_count == 0:

        print(
            "처리할 Report가 없습니다."
        )

        print(
            "모든 상세정보가 "
            "적재된 상태입니다."
        )

        return

    # -----------------------------------------------------
    # 상세정보 적재
    # -----------------------------------------------------

    success_count = 0
    fail_count = 0

    failed_report_ids = []

    for index, report_id in enumerate(
        report_ids,
        start=1
    ):

        print("-" * 60)

        print(
            f"[{index}/{target_count}] "
            f"report_id={report_id}"
        )

        print("-" * 60)

        success = load_report_detail(
            report_id
        )

        if success:

            success_count += 1

        else:

            fail_count += 1

            failed_report_ids.append(
                report_id
            )

        # 마지막 Report가 아니면
        # 다음 요청 전 잠시 대기
        if index < target_count:

            time.sleep(
                REQUEST_DELAY
            )

        print()

    # -----------------------------------------------------
    # 결과
    # -----------------------------------------------------

    remaining_count = (
        get_remaining_count()
    )

    elapsed_time = (
        time.time()
        - start_time
    )

    print("=" * 60)
    print(
        "WAHIS 상세정보 초기 적재 완료"
    )
    print("=" * 60)

    print(
        f"이번 실행 대상: "
        f"{target_count}건"
    )

    print(
        f"성공: "
        f"{success_count}건"
    )

    print(
        f"실패: "
        f"{fail_count}건"
    )

    print(
        f"남은 미처리 Report: "
        f"{remaining_count}건"
    )

    print(
        f"실행 시간: "
        f"{elapsed_time:.1f}초"
    )

    # -----------------------------------------------------
    # 실패 Report 출력
    # -----------------------------------------------------

    if failed_report_ids:

        print()
        print(
            "실패 Report ID:"
        )

        for report_id in (
            failed_report_ids
        ):

            print(
                f"- {report_id}"
            )


if __name__ == "__main__":
    main()