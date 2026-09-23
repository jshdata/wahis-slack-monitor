from datetime import datetime
from zoneinfo import ZoneInfo

from database.db import get_connection


# =========================================================
# 시간대
# =========================================================

KST = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")


# =========================================================
# 질병 약어 → DB 실제 질병명
# =========================================================

DISEASE_MAP = {
    "HPAI": [
        (
            "High pathogenicity avian influenza viruses "
            "(Inf. with) (poultry)"
        ),
        (
            "Influenza A viruses of high pathogenicity "
            "(Inf. with) "
            "(non-poultry including wild birds) (2017-)"
        ),
    ],

    "ASF": [
        "African swine fever virus (Inf. with)"
    ],

    "FMD": [
        "Foot and mouth disease virus (Inf. with)"
    ],

    "LSD": [
        "Lumpy skin disease virus (Inf. with)"
    ],
}


# =========================================================
# Slack에서 '기타' 선택 시 포함할 DB 권역
# =========================================================

OTHER_REGIONS = [
    "North America",
    "South America",
    "Oceania",
]


# =========================================================
# KST → DB UTC 변환
# =========================================================

def kst_to_db_utc(value):
    """
    한국시간(KST)을 현재 DB에 저장된 UTC 기준 datetime으로 변환한다.

    Parameters
    ----------
    value : datetime | str

        datetime 또는 다음 형식의 문자열 사용 가능

        2026-09-22 09:00
        2026-09-22 09:00:00

    Returns
    -------
    datetime

        timezone 정보가 제거된 UTC datetime

    예
    --
    2026-09-22 09:00 KST
        ↓
    2026-09-22 00:00 UTC
    """

    if value is None:
        return None

    if isinstance(value, str):

        value = datetime.fromisoformat(
            value
        )

    # timezone 정보가 없는 입력은
    # 사용자가 입력한 한국시간으로 간주
    if value.tzinfo is None:

        value = value.replace(
            tzinfo=KST
        )

    # UTC 변환
    utc_value = value.astimezone(
        UTC
    )

    # 현재 MySQL에는 timezone 없는
    # UTC datetime으로 저장되어 있으므로 tzinfo 제거
    return utc_value.replace(
        tzinfo=None
    )


# =========================================================
# DB UTC → KST 변환
# =========================================================

def db_utc_to_kst(value):
    """
    현재 DB에 저장된 UTC datetime을
    한국시간(KST)으로 변환한다.

    예
    --
    DB:
    2026-09-21 10:20:38

        ↓

    KST:
    2026-09-21 19:20:38
    """

    if value is None:
        return None

    # DB datetime은 timezone 정보가 없지만
    # 실제 의미는 UTC
    if value.tzinfo is None:

        value = value.replace(
            tzinfo=UTC
        )

    return value.astimezone(
        KST
    )


# =========================================================
# 국가 목록
# =========================================================

def get_countries(region=None):
    """
    국가 목록 조회

    region:
        None   -> 전체 국가
        Asia
        Europe
        Africa
        Other  -> North America + South America + Oceania
    """

    conn = None
    cursor = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        sql = """
            SELECT country
            FROM country_regions
            WHERE 1 = 1
        """

        params = []

        if region:

            if region == "Other":

                placeholders = ", ".join(
                    ["%s"] * len(OTHER_REGIONS)
                )

                sql += f"""
                    AND region IN ({placeholders})
                """

                params.extend(
                    OTHER_REGIONS
                )

            else:

                sql += """
                    AND region = %s
                """

                params.append(
                    region
                )

        sql += """
            ORDER BY country
        """

        cursor.execute(
            sql,
            params
        )

        rows = cursor.fetchall()

        return [
            row[0]
            for row in rows
        ]

    finally:

        if cursor is not None:
            cursor.close()

        if conn is not None:
            conn.close()


# =========================================================
# WAHIS Report 검색
# =========================================================

def search_reports(
    region=None,
    country=None,
    wild=None,
    disease=None,
    year=None,
    month=None,
    start_datetime=None,
    end_datetime=None,
    limit=100,
):
    """
    WAHIS Report 검색

    Parameters
    ----------
    region : str | None
        Asia / Europe / Africa / Other

    country : str | None
        WAHIS DB에 저장된 국가명

    wild : bool | None
        True  = 야생
        False = 사육
        None  = 전체

    disease : str | None
        HPAI / ASF / FMD / LSD

    year : int | None
        기존 연도 조회 기능

    month : int | None
        기존 월 조회 기능

    start_datetime : datetime | str | None
        조회 시작 시각 (KST)

        예:
        2026-09-22 09:00

    end_datetime : datetime | str | None
        조회 종료 시각 (KST)

        예:
        2026-09-23 09:00

    limit : int
        최대 조회 건수


    시간 범위 규칙
    -------------
    start_datetime <= submission_date < end_datetime

    즉 종료 시각은 포함하지 않는다.

    예:
    9월 22일 09:00 KST
        ~
    9월 23일 09:00 KST

    DB에서는 자동으로

    9월 22일 00:00 UTC
        ~
    9월 23일 00:00 UTC

    로 조회한다.
    """

    conn = None
    cursor = None

    try:

        conn = get_connection()
        cursor = conn.cursor()

        sql = """
            SELECT
                dr.report_id,
                dr.event_id,
                dr.country,
                cr.region,
                dr.disease,
                dr.submission_date,
                dr.report_type,
                dr.report_status
            FROM disease_reports dr

            JOIN country_regions cr
                ON dr.country = cr.country

            WHERE 1 = 1
        """

        params = []

        # -------------------------------------------------
        # 권역
        # -------------------------------------------------

        if region:

            if region == "Other":

                placeholders = ", ".join(
                    ["%s"] * len(OTHER_REGIONS)
                )

                sql += f"""
                    AND cr.region IN ({placeholders})
                """

                params.extend(
                    OTHER_REGIONS
                )

            else:

                sql += """
                    AND cr.region = %s
                """

                params.append(
                    region
                )

        # -------------------------------------------------
        # 국가
        # -------------------------------------------------

        if country:

            sql += """
                AND dr.country = %s
            """

            params.append(
                country
            )

        # -------------------------------------------------
        # 질병
        #
        # HPAI는
        # 668 가금 + 671 가금 외
        # 두 질병을 함께 조회
        # -------------------------------------------------

        if disease:

            disease_code = disease.upper()

            if disease_code not in DISEASE_MAP:

                raise ValueError(
                    f"지원하지 않는 질병 코드입니다: {disease}"
                )

            disease_names = DISEASE_MAP[
                disease_code
            ]

            placeholders = ", ".join(
                ["%s"] * len(disease_names)
            )

            sql += f"""
                AND dr.disease IN ({placeholders})
            """

            params.extend(
                disease_names
            )

        # -------------------------------------------------
        # 야생 / 사육
        #
        # JOIN 대신 EXISTS 사용
        # → 같은 Report에 여러 quantitative 행이 있어도
        #   Report가 중복 출력되지 않음
        # -------------------------------------------------

        if wild is not None:

            sql += """
                AND EXISTS (
                    SELECT 1
                    FROM report_quantitative rq
                    WHERE rq.report_id = dr.report_id
                      AND rq.is_wild = %s
                )
            """

            params.append(
                1 if wild else 0
            )

        # -------------------------------------------------
        # 기존 연도
        # -------------------------------------------------

        if year is not None:

            sql += """
                AND YEAR(dr.submission_date) = %s
            """

            params.append(
                int(year)
            )

        # -------------------------------------------------
        # 기존 월
        # -------------------------------------------------

        if month is not None:

            month = int(month)

            if month < 1 or month > 12:

                raise ValueError(
                    "month는 1~12 사이여야 합니다."
                )

            sql += """
                AND MONTH(dr.submission_date) = %s
            """

            params.append(
                month
            )

        # -------------------------------------------------
        # KST 시작 시각
        # -------------------------------------------------

        if start_datetime is not None:

            start_utc = kst_to_db_utc(
                start_datetime
            )

            sql += """
                AND dr.submission_date >= %s
            """

            params.append(
                start_utc
            )

        # -------------------------------------------------
        # KST 종료 시각
        #
        # 종료 시각은 포함하지 않는다.
        # -------------------------------------------------

        if end_datetime is not None:

            end_utc = kst_to_db_utc(
                end_datetime
            )

            sql += """
                AND dr.submission_date < %s
            """

            params.append(
                end_utc
            )

        # -------------------------------------------------
        # 정렬 + 제한
        # -------------------------------------------------

        sql += """
            ORDER BY dr.submission_date DESC
            LIMIT %s
        """

        params.append(
            int(limit)
        )

        cursor.execute(
            sql,
            params
        )

        rows = cursor.fetchall()

        return rows

    finally:

        if cursor is not None:
            cursor.close()

        if conn is not None:
            conn.close()


# =========================================================
# 테스트
# =========================================================

if __name__ == "__main__":

    print("=" * 60)
    print("WAHIS KST 시간 범위 조회 테스트")
    print("=" * 60)

    # -----------------------------------------------------
    # 테스트 범위
    #
    # 한국시간:
    # 2026-09-21 09:00
    #     ~
    # 2026-09-22 09:00
    #
    # DB UTC:
    # 2026-09-21 00:00
    #     ~
    # 2026-09-22 00:00
    # -----------------------------------------------------

    start_kst = "2026-09-21 09:00:00"
    end_kst = "2026-09-22 09:00:00"

    print()
    print(
        "조회 범위 (KST):",
        start_kst,
        "~",
        end_kst
    )

    print(
        "DB 시작시간 (UTC):",
        kst_to_db_utc(start_kst)
    )

    print(
        "DB 종료시간 (UTC):",
        kst_to_db_utc(end_kst)
    )

    results = search_reports(
        start_datetime=start_kst,
        end_datetime=end_kst,
        limit=100,
    )

    print()
    print(
        f"조회 결과: {len(results)}건"
    )
    print()

    for row in results:

        submission_utc = row[5]

        submission_kst = db_utc_to_kst(
            submission_utc
        )

        print(
            row[0],   # report_id
            row[2],   # country
            row[4],   # disease
            "UTC:",
            submission_utc,
            "KST:",
            submission_kst.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        )