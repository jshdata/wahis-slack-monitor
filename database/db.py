import os
from datetime import datetime

import pymysql
from dotenv import load_dotenv


load_dotenv()


def get_connection():
    """
    Aiven MySQL 연결

    connect_timeout:
        DB 서버와 최초 연결을 맺는 최대 대기시간

    read_timeout:
        SQL 실행 후 DB 응답을 기다리는 최대 시간

    write_timeout:
        DB로 데이터를 전송할 때의 최대 대기시간

    원격 Aiven DB에 대량 데이터를 저장할 수 있으므로
    read/write timeout은 120초로 설정한다.
    """

    return pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),

        charset="utf8mb4",

        connect_timeout=10,
        read_timeout=120,
        write_timeout=120,

        ssl={
            "ca": os.getenv("DB_SSL_CA")
        }
    )


def convert_datetime(date_string):
    """
    WAHIS 날짜 문자열을 MySQL DATETIME으로 변환
    """

    if not date_string:
        return None

    return datetime.fromisoformat(
        date_string
    ).replace(tzinfo=None)


def is_report_exists(report_id):
    """
    단일 report_id가 DB에 존재하는지 확인

    기존 코드와의 호환성을 위해 유지한다.
    운영 모니터링에서는
    get_existing_report_ids() 사용을 권장한다.
    """

    conn = None
    cursor = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        sql = """
        SELECT report_id
        FROM disease_reports
        WHERE report_id = %s
        """

        cursor.execute(
            sql,
            (report_id,)
        )

        result = cursor.fetchone()

        return result is not None

    except pymysql.MySQLError as e:

        print(
            "리포트 조회 실패:",
            e
        )

        raise

    finally:

        if cursor:

            try:
                cursor.close()

            except Exception:
                pass

        if conn:

            try:
                conn.close()

            except Exception:
                pass


def get_existing_report_ids(report_ids):
    """
    여러 report_id를 한 번의 DB 조회로 확인한다.

    Parameters
    ----------
    report_ids : list
        확인할 WAHIS report_id 목록

    Returns
    -------
    set
        DB에 이미 존재하는 report_id 집합

    예:
        입력:
        [185963, 185940, 185955]

        DB에 185940, 185955가 존재한다면:

        반환:
        {185940, 185955}
    """

    if not report_ids:
        return set()

    conn = None
    cursor = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        placeholders = ", ".join(
            ["%s"] * len(report_ids)
        )

        sql = f"""
        SELECT report_id
        FROM disease_reports
        WHERE report_id IN ({placeholders})
        """

        cursor.execute(
            sql,
            tuple(report_ids)
        )

        results = cursor.fetchall()

        existing_ids = {
            row[0]
            for row in results
        }

        return existing_ids

    except pymysql.MySQLError as e:

        print(
            "리포트 일괄 조회 실패:",
            e
        )

        raise

    finally:

        if cursor:

            try:
                cursor.close()

            except Exception:
                pass

        if conn:

            try:
                conn.close()

            except Exception:
                pass


def insert_disease_report(event):
    """
    WAHIS 이벤트를 DB에 저장
    """

    conn = None
    cursor = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        sql = """
        INSERT INTO disease_reports (
            report_id,
            event_id,
            country,
            disease,
            submission_date
        )
        VALUES (%s, %s, %s, %s, %s)

        ON DUPLICATE KEY UPDATE
            event_id = VALUES(event_id),
            country = VALUES(country),
            disease = VALUES(disease),
            submission_date = VALUES(submission_date)
        """

        submission_date = convert_datetime(
            event["submissionDate"]
        )

        cursor.execute(
            sql,
            (
                event["reportId"],
                event["eventId"],
                event["country"],
                event["disease"],
                submission_date
            )
        )

        conn.commit()

        print(
            f"DB 저장 성공: "
            f"report_id={event['reportId']}"
        )

    except pymysql.MySQLError as e:

        if conn:

            try:
                conn.rollback()

            except Exception as rollback_error:

                print(
                    "rollback 생략 "
                    "(DB 연결이 이미 종료되었을 수 있음):",
                    repr(rollback_error)
                )

        print(
            "DB 저장 실패:",
            e
        )

        raise

    finally:

        if cursor:

            try:
                cursor.close()

            except Exception:
                pass

        if conn:

            try:
                conn.close()

            except Exception:
                pass


if __name__ == "__main__":

    try:

        conn = get_connection()

        print(
            "DB 연결 성공"
        )

        conn.close()

    except pymysql.MySQLError as e:

        print(
            "DB 연결 실패:",
            e
        )

        raise