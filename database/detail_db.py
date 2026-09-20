from datetime import datetime

from database.db import get_connection
from wahis.detail_api import get_report_detail


def convert_datetime(date_string):
    """
    WAHIS ISO 날짜 문자열을 MySQL DATETIME으로 변환한다.
    """

    if not date_string:
        return None

    return datetime.fromisoformat(
        date_string
    ).replace(tzinfo=None)


def get_translation(value):
    """
    WAHIS 값이 dict이면 translation 값을 반환한다.
    문자열이면 문자열 자체를 반환한다.
    None이면 None을 반환한다.
    """

    if value is None:
        return None

    if isinstance(value, dict):
        return (
            value.get("translation")
            or value.get("name")
            or value.get("keyValue")
        )

    return value


def get_subtype(event):
    """
    event.subType 구조에서 subtype 이름을 가져온다.
    """

    subtype_data = event.get("subType")

    if not subtype_data:
        return None

    if isinstance(subtype_data, str):
        return subtype_data

    if not isinstance(subtype_data, dict):
        return None

    disease_data = subtype_data.get("disease")

    if isinstance(disease_data, dict):
        return (
            disease_data.get("name")
            or disease_data.get("translation")
        )

    return (
        subtype_data.get("name")
        or subtype_data.get("translation")
    )


def get_unit(quantitative):
    """
    quantitativeData.unit에서 단위를 가져온다.
    """

    unit_data = quantitative.get("unit")

    if unit_data is None:
        return None

    if isinstance(unit_data, dict):
        return (
            unit_data.get("translation")
            or unit_data.get("keyValue")
        )

    return str(unit_data)


def safe_rollback(conn):
    """
    DB 오류로 연결이 이미 끊어진 경우
    rollback() 자체가 또 다른 예외를 발생시킬 수 있다.

    rollback 실패가 원래 오류를 덮지 않도록
    안전하게 처리한다.
    """

    if conn is None:
        return

    try:
        conn.rollback()

    except Exception as rollback_error:
        print(
            "rollback 생략 "
            "(DB 연결이 이미 종료되었을 수 있음): "
            f"{repr(rollback_error)}"
        )


def safe_close(cursor, conn):
    """
    cursor / connection 종료 중 발생하는 예외가
    원래 처리 결과에 영향을 주지 않도록 한다.
    """

    if cursor is not None:

        try:
            cursor.close()

        except Exception:
            pass

    if conn is not None:

        try:
            conn.close()

        except Exception:
            pass


def update_disease_report_detail(data):
    """
    상세 API 데이터를 이용해
    기존 disease_reports를 보완한다.

    detail_loaded는 여기서 변경하지 않는다.

    outbreaks와 quantitative까지 모두 저장된 뒤
    save_report_detail() 마지막 단계에서 1로 변경한다.
    """

    event = data.get("event") or {}
    report = data.get("report") or {}

    report_id = report.get("reportId")

    if report_id is None:
        raise ValueError(
            "상세 API 응답에 reportId가 없습니다."
        )

    subtype = get_subtype(event)

    event_status = get_translation(
        event.get("eventStatus")
    )

    reason = get_translation(
        event.get("reason")
    )

    report_status = get_translation(
        report.get("reportStatus")
    )

    sql = """
        UPDATE disease_reports
        SET
            subtype = %s,
            event_start_date = %s,
            event_status = %s,
            reason = %s,
            report_status = %s,
            report_number = %s,
            is_aquatic = %s
        WHERE report_id = %s
    """

    values = (
        subtype,
        convert_datetime(
            event.get("startedOn")
        ),
        event_status,
        reason,
        report_status,
        report.get("reportNumber"),
        event.get("isAquatic"),
        report_id
    )

    conn = None
    cursor = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            sql,
            values
        )

        conn.commit()

        print(
            "disease_reports 상세정보 업데이트 성공: "
            f"report_id={report_id}"
        )

    except Exception:

        safe_rollback(conn)
        raise

    finally:

        safe_close(
            cursor,
            conn
        )


def get_existing_outbreak_versions(
    cursor,
    outbreak_ids
):
    """
    이번 Report에 포함된 outbreak들의
    현재 DB last_update_report_id를
    한 번의 SELECT로 조회한다.

    반환 예:
    {
        12345: 185612,
        12346: 185953
    }

    기존 방식:
        outbreak마다 SELECT 1번

    개선 방식:
        Report당 SELECT 1번
    """

    if not outbreak_ids:
        return {}

    placeholders = ", ".join(
        ["%s"] * len(outbreak_ids)
    )

    sql = f"""
        SELECT
            outbreak_id,
            last_update_report_id
        FROM outbreaks
        WHERE outbreak_id IN ({placeholders})
    """

    cursor.execute(
        sql,
        tuple(outbreak_ids)
    )

    rows = cursor.fetchall()

    return {
        row[0]: row[1]
        for row in rows
    }


def insert_outbreaks(data):
    """
    상세 API의 outbreaks 데이터를 저장한다.

    동일 outbreak_id가 존재할 경우:

    incoming last_update_report_id가
    기존 DB의 last_update_report_id보다
    오래된 경우 UPDATE하지 않는다.

    또한 기존처럼 outbreak 하나마다
    SELECT하지 않고 이번 Report의 outbreak를
    한 번에 조회하여 DB 왕복 횟수를 줄인다.
    """

    event = data.get("event") or {}

    event_id = event.get("eventId")

    outbreaks = data.get("outbreaks") or []

    # -----------------------------------------------------
    # outbreak가 없는 Report
    # -----------------------------------------------------

    if not outbreaks:

        print(
            "outbreaks 저장 성공: 0건"
        )

        return

    # -----------------------------------------------------
    # 유효한 outbreak만 추출
    # -----------------------------------------------------

    valid_outbreaks = []

    for outbreak in outbreaks:

        outbreak_id = outbreak.get(
            "outbreakId"
        )

        if outbreak_id is None:

            print(
                "outbreakId가 없어 "
                "해당 outbreak를 건너뜁니다."
            )

            continue

        valid_outbreaks.append(
            outbreak
        )

    if not valid_outbreaks:

        print(
            "outbreaks 저장 성공: 0건"
        )

        return

    outbreak_ids = [
        outbreak.get("outbreakId")
        for outbreak in valid_outbreaks
    ]

    # -----------------------------------------------------
    # UPSERT SQL
    # -----------------------------------------------------

    upsert_sql = """
        INSERT INTO outbreaks (
            outbreak_id,
            event_id,
            created_by_report_id,
            last_update_report_id,
            oie_reference,
            national_reference,
            admin_division,
            location,
            location_approx,
            epi_unit_type,
            cluster_count,
            start_date,
            end_date,
            longitude,
            latitude,
            description,
            species_number
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s
        )
        ON DUPLICATE KEY UPDATE
            event_id =
                VALUES(event_id),

            created_by_report_id =
                VALUES(created_by_report_id),

            last_update_report_id =
                VALUES(last_update_report_id),

            oie_reference =
                VALUES(oie_reference),

            national_reference =
                VALUES(national_reference),

            admin_division =
                VALUES(admin_division),

            location =
                VALUES(location),

            location_approx =
                VALUES(location_approx),

            epi_unit_type =
                VALUES(epi_unit_type),

            cluster_count =
                VALUES(cluster_count),

            start_date =
                VALUES(start_date),

            end_date =
                VALUES(end_date),

            longitude =
                VALUES(longitude),

            latitude =
                VALUES(latitude),

            description =
                VALUES(description),

            species_number =
                VALUES(species_number)
    """

    conn = None
    cursor = None

    saved_count = 0
    skipped_old_count = 0

    try:

        conn = get_connection()
        cursor = conn.cursor()

        # -------------------------------------------------
        # 기존 outbreak 상태를 한 번에 조회
        # -------------------------------------------------

        existing_versions = (
            get_existing_outbreak_versions(
                cursor,
                outbreak_ids
            )
        )

        # -------------------------------------------------
        # 메모리에서 최신성 비교
        # -------------------------------------------------

        values_list = []

        for outbreak in valid_outbreaks:

            outbreak_id = outbreak.get(
                "outbreakId"
            )

            incoming_last_update_report_id = (
                outbreak.get(
                    "lastUpdateReportId"
                )
            )

            existing_last_update_report_id = (
                existing_versions.get(
                    outbreak_id
                )
            )

            # ---------------------------------------------
            # 기존 값과 incoming 값이 모두 있는 경우
            # 과거 데이터가 최신 데이터를 덮어쓰지 못하게 한다.
            # ---------------------------------------------

            if (
                existing_last_update_report_id
                is not None
                and incoming_last_update_report_id
                is not None
                and incoming_last_update_report_id
                < existing_last_update_report_id
            ):

                skipped_old_count += 1
                continue

            values = (
                outbreak_id,
                event_id,
                outbreak.get(
                    "createdByReportId"
                ),
                incoming_last_update_report_id,
                outbreak.get(
                    "oieReference"
                ),
                outbreak.get(
                    "nationalReference"
                ),
                outbreak.get(
                    "adminDivision"
                ),
                outbreak.get(
                    "location"
                ),
                outbreak.get(
                    "locationApprox"
                ),
                outbreak.get(
                    "epiUnitType"
                ),
                outbreak.get(
                    "clusterCount"
                ),
                convert_datetime(
                    outbreak.get(
                        "startDate"
                    )
                ),
                convert_datetime(
                    outbreak.get(
                        "endDate"
                    )
                ),
                outbreak.get(
                    "longitude"
                ),
                outbreak.get(
                    "latitude"
                ),
                outbreak.get(
                    "description"
                ),
                outbreak.get(
                    "speciesNumber"
                )
            )

            values_list.append(
                values
            )

        # -------------------------------------------------
        # executemany로 한 번에 UPSERT
        # -------------------------------------------------

        if values_list:

            cursor.executemany(
                upsert_sql,
                values_list
            )

            saved_count = len(
                values_list
            )

        conn.commit()

        print(
            "outbreaks 저장 성공: "
            f"{saved_count}건"
        )

        if skipped_old_count > 0:

            print(
                "과거 outbreak 업데이트 건너뜀: "
                f"{skipped_old_count}건"
            )

    except Exception:

        safe_rollback(conn)
        raise

    finally:

        safe_close(
            cursor,
            conn
        )


def insert_quantitative_data(data):
    """
    quantitativeData 저장.

    news:
        data_type = 'new'

    totals:
        data_type = 'total'
    """

    report = data.get("report") or {}

    quantitative = (
        data.get("quantitativeData")
        or {}
    )

    report_id = report.get("reportId")

    if report_id is None:
        raise ValueError(
            "상세 API 응답에 reportId가 없습니다."
        )

    unit = get_unit(
        quantitative
    )

    sql = """
        INSERT INTO report_quantitative (
            report_id,
            data_type,
            outbreak_quantities_id,
            species_id,
            species_name,
            is_wild,
            susceptible,
            cases,
            deaths,
            killed,
            slaughtered,
            vaccinated,
            unit
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            species_id =
                VALUES(species_id),

            species_name =
                VALUES(species_name),

            is_wild =
                VALUES(is_wild),

            susceptible =
                VALUES(susceptible),

            cases =
                VALUES(cases),

            deaths =
                VALUES(deaths),

            killed =
                VALUES(killed),

            slaughtered =
                VALUES(slaughtered),

            vaccinated =
                VALUES(vaccinated),

            unit =
                VALUES(unit)
    """

    data_groups = [
        (
            "new",
            quantitative.get("news") or []
        ),
        (
            "total",
            quantitative.get("totals") or []
        )
    ]

    values_list = []

    for data_type, items in data_groups:

        for item in items:

            values = (
                report_id,
                data_type,
                item.get(
                    "outbreakQuantitiesId"
                ),
                item.get(
                    "speciesId"
                ),
                item.get(
                    "speciesName"
                ),
                item.get(
                    "isWild"
                ),
                item.get(
                    "susceptible"
                ),
                item.get(
                    "cases"
                ),
                item.get(
                    "deaths"
                ),
                item.get(
                    "killed"
                ),
                item.get(
                    "slaughtered"
                ),
                item.get(
                    "vaccinated"
                ),
                unit
            )

            values_list.append(
                values
            )

    # -----------------------------------------------------
    # quantitative가 없는 경우
    # -----------------------------------------------------

    if not values_list:

        print(
            "report_quantitative 저장 성공: 0건"
        )

        return

    conn = None
    cursor = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        # 기존처럼 한 행씩 execute하지 않고
        # 한 번의 executemany로 처리
        cursor.executemany(
            sql,
            values_list
        )

        conn.commit()

        print(
            "report_quantitative 저장 성공: "
            f"{len(values_list)}건"
        )

    except Exception:

        safe_rollback(conn)
        raise

    finally:

        safe_close(
            cursor,
            conn
        )


def mark_detail_loaded(report_id):
    """
    상세 데이터 전체 저장이 성공한 Report를
    처리 완료 상태로 변경한다.
    """

    sql = """
        UPDATE disease_reports
        SET detail_loaded = 1
        WHERE report_id = %s
    """

    conn = None
    cursor = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            sql,
            (report_id,)
        )

        conn.commit()

        print(
            "상세정보 처리 완료 표시: "
            f"report_id={report_id}"
        )

    except Exception:

        safe_rollback(conn)
        raise

    finally:

        safe_close(
            cursor,
            conn
        )


def save_report_detail(data):
    """
    WAHIS 상세정보 전체 저장.

    처리 순서:

    1. disease_reports 상세정보 UPDATE
    2. outbreaks 저장
    3. quantitative 저장
    4. 모든 과정이 성공한 경우
       detail_loaded = 1
    """

    report = data.get("report") or {}

    report_id = report.get(
        "reportId"
    )

    if report_id is None:

        raise ValueError(
            "상세 API 응답에 reportId가 없습니다."
        )

    update_disease_report_detail(
        data
    )

    insert_outbreaks(
        data
    )

    insert_quantitative_data(
        data
    )

    mark_detail_loaded(
        report_id
    )


if __name__ == "__main__":

    TEST_REPORT_ID = 185953

    print("=" * 60)

    print(
        "상세정보 DB 저장 테스트: "
        f"{TEST_REPORT_ID}"
    )

    print("=" * 60)

    detail = get_report_detail(
        TEST_REPORT_ID
    )

    save_report_detail(
        detail
    )

    print()

    print("=" * 60)

    print(
        "상세정보 DB 저장 테스트 완료"
    )

    print("=" * 60)