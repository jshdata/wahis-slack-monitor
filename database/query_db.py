from database.db import get_connection


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

                params.extend(OTHER_REGIONS)

            else:
                sql += """
                    AND region = %s
                """
                params.append(region)

        sql += """
            ORDER BY country
        """

        cursor.execute(sql, params)

        rows = cursor.fetchall()

        return [row[0] for row in rows]

    finally:
        if cursor is not None:
            cursor.close()

        if conn is not None:
            conn.close()

def search_reports(
    region=None,
    country=None,
    wild=None,
    disease=None,
    year=None,
    month=None,
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
        예: 2026

    month : int | None
        1 ~ 12

    limit : int
        최대 조회 건수
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

                params.extend(OTHER_REGIONS)

            else:
                sql += """
                    AND cr.region = %s
                """
                params.append(region)

        # -------------------------------------------------
        # 국가
        # -------------------------------------------------
        if country:
            sql += """
                AND dr.country = %s
            """
            params.append(country)

        # -------------------------------------------------
        # 질병
        # -------------------------------------------------

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
        # 연도
        # -------------------------------------------------
        if year is not None:
            sql += """
                AND YEAR(dr.submission_date) = %s
            """
            params.append(int(year))

        # -------------------------------------------------
        # 월
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
            params.append(month)

        # -------------------------------------------------
        # 정렬 + 제한
        # -------------------------------------------------
        sql += """
            ORDER BY dr.submission_date DESC
            LIMIT %s
        """

        params.append(int(limit))

        cursor.execute(sql, params)

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
    print("WAHIS HPAI 668 + 671 통합 조회 테스트")
    print("=" * 60)

    results = search_reports(
        disease="HPAI",
        year=2026,
        limit=20,
    )

    print(
        f"\n조회 결과: {len(results)}건\n"
    )

    for row in results:

        print(
            row[0],  # report_id
            row[2],  # country
            row[4],  # disease
            row[5],  # submission_date
        )