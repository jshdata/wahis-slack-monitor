# database/stats_db.py

from database.db import get_connection


# =========================================================
# 질병 이름 매핑
# =========================================================

DISEASE_MAP = {
    "HPAI": (
        "High pathogenicity avian influenza viruses "
        "(Inf. with) (poultry)"
    ),
    "HPAI_NON_POULTRY": (
        "Influenza A viruses of high pathogenicity "
        "(Inf. with) "
        "(non-poultry including wild birds) (2017-)"
    ),
    "ASF": "African swine fever virus (Inf. with)",
    "FMD": "Foot and mouth disease virus (Inf. with)",
    "LSD": "Lumpy skin disease virus (Inf. with)",
}


# =========================================================
# 국가 × 세부질병(subtype)별 발생건수 조회
# =========================================================

def get_outbreak_stats(
    disease_code,
    start_date,
    end_date,
    region=None,
    country=None,
):
    """
    outbreak.start_date 기준 발생건수를 조회한다.

    반환:
        country
        region
        subtype
        outbreak_count
    """

    disease_name = DISEASE_MAP.get(
        disease_code
    )

    if disease_name is None:
        raise ValueError(
            "지원하지 않는 질병 코드입니다: "
            f"{disease_code}"
        )

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            # ---------------------------------------------
            # 기본 WHERE 조건
            # ---------------------------------------------

            conditions = [
                "dr.disease = %s"
            ]

            params = [
                disease_name
            ]

            # ---------------------------------------------
            # 지역 필터
            # ---------------------------------------------

            if region:

                conditions.append(
                    "cr.region = %s"
                )

                params.append(
                    region
                )

            # ---------------------------------------------
            # 국가 필터
            # ---------------------------------------------

            if country:

                conditions.append(
                    "dr.country = %s"
                )

                params.append(
                    country
                )

            where_clause = " AND ".join(
                conditions
            )

            # ---------------------------------------------
            # 발생건수 조회
            #
            # Event별
            # country / region / subtype 확보
            #
            # 이후 outbreak.start_date 기준
            # 고유 outbreak 집계
            # ---------------------------------------------

            sql = f"""
                WITH target_events AS (
                    SELECT
                        dr.event_id,
                        MAX(dr.country) AS country,
                        MAX(cr.region) AS region,
                        MAX(dr.subtype) AS subtype

                    FROM disease_reports dr

                    LEFT JOIN country_regions cr
                        ON dr.country = cr.country

                    WHERE {where_clause}

                    GROUP BY
                        dr.event_id
                )

                SELECT
                    te.country,
                    te.region,

                    COALESCE(
                        te.subtype,
                        '미분류'
                    ) AS subtype,

                    COUNT(
                        DISTINCT o.outbreak_id
                    ) AS outbreak_count

                FROM outbreaks o

                JOIN target_events te
                    ON o.event_id = te.event_id

                WHERE
                    o.start_date >= %s

                    AND o.start_date
                        < DATE_ADD(
                            %s,
                            INTERVAL 1 DAY
                        )

                GROUP BY
                    te.country,
                    te.region,

                    COALESCE(
                        te.subtype,
                        '미분류'
                    )

                ORDER BY
                    te.country,
                    subtype
            """

            params.extend([
                start_date,
                end_date,
            ])

            cursor.execute(
                sql,
                params
            )

            rows = cursor.fetchall()

            return rows

    finally:

        conn.close()


# =========================================================
# HPAI 가금 / 가금 외 발생건수 조회
# =========================================================

def get_hpai_outbreak_stats(
    start_date,
    end_date,
    region=None,
    country=None,
):
    """
    HPAI를 두 종류로 나누어 조회한다.

    poultry
        HPAI 가금

    non_poultry
        HPAI 가금 외
        (non-poultry including wild birds)

    야생/사육 분류와는 별개의 구분이다.
    """

    poultry_rows = get_outbreak_stats(
        disease_code="HPAI",
        start_date=start_date,
        end_date=end_date,
        region=region,
        country=country,
    )

    non_poultry_rows = get_outbreak_stats(
        disease_code="HPAI_NON_POULTRY",
        start_date=start_date,
        end_date=end_date,
        region=region,
        country=country,
    )

    return {
        "poultry": poultry_rows,
        "non_poultry": non_poultry_rows,
    }


# =========================================================
# Matrix 형태로 변환
# =========================================================

def build_matrix(rows):
    """
    DB 조회 결과를 Matrix 형태로 변환한다.

    국가별 Matrix와 함께
    권역별 합계 Matrix도 생성한다.

    반환:

    {
        "countries": [...],
        "subtypes": [...],

        "matrix": {
            "Korea (Rep. of)": {
                "H5N1": 87
            }
        },

        "country_totals": {...},

        "region_matrix": {
            "Asia": {
                "H5N1": 500
            }
        },

        "region_totals": {...},

        "subtype_totals": {...},

        "grand_total": 0
    }
    """

    # =====================================================
    # 기본 자료구조
    # =====================================================

    countries = set()
    subtypes = set()

    matrix = {}

    region_matrix = {}

    # =====================================================
    # Matrix 생성
    # =====================================================

    for row in rows:

        country = row[0]
        region = row[1]
        subtype = row[2]
        count = int(
            row[3]
        )

        # ---------------------------------------------
        # 국가 / subtype 목록
        # ---------------------------------------------

        countries.add(
            country
        )

        subtypes.add(
            subtype
        )

        # ---------------------------------------------
        # 국가 × subtype Matrix
        # ---------------------------------------------

        if country not in matrix:

            matrix[country] = {}

        matrix[country][subtype] = (
            count
        )

        # ---------------------------------------------
        # 권역값이 없는 경우
        # ---------------------------------------------

        if not region:

            region = "Other"

        # ---------------------------------------------
        # 권역 × subtype Matrix
        # ---------------------------------------------

        if region not in region_matrix:

            region_matrix[region] = {}

        region_matrix[region][subtype] = (
            region_matrix[region]
            .get(
                subtype,
                0
            )
            + count
        )

    # =====================================================
    # 국가 정렬
    # =====================================================

    countries = sorted(
        countries
    )

    # =====================================================
    # subtype 정렬
    #
    # 미분류는 가장 마지막
    # =====================================================

    subtypes = sorted(
        subtypes,
        key=lambda x: (
            x == "미분류",
            x
        )
    )

    # =====================================================
    # 국가별 합계
    # =====================================================

    country_totals = {}

    for country in countries:

        country_totals[country] = sum(
            matrix
            .get(
                country,
                {}
            )
            .values()
        )

    # =====================================================
    # 권역별 합계
    # =====================================================

    region_totals = {}

    for region in region_matrix:

        region_totals[region] = sum(
            region_matrix[
                region
            ].values()
        )

    # =====================================================
    # subtype별 전체 합계
    # =====================================================

    subtype_totals = {}

    for subtype in subtypes:

        subtype_totals[subtype] = sum(
            matrix
            .get(
                country,
                {}
            )
            .get(
                subtype,
                0
            )

            for country in countries
        )

    # =====================================================
    # 전체 발생건수
    # =====================================================

    grand_total = sum(
        country_totals.values()
    )

    # =====================================================
    # 반환
    # =====================================================

    return {
        "countries": countries,
        "subtypes": subtypes,
        "matrix": matrix,
        "country_totals": country_totals,

        "region_matrix": region_matrix,
        "region_totals": region_totals,

        "subtype_totals": subtype_totals,
        "grand_total": grand_total,
    }


# =========================================================
# Matrix 콘솔 출력
# =========================================================

def print_matrix(
    result,
    title=None,
):

    countries = result[
        "countries"
    ]

    subtypes = result[
        "subtypes"
    ]

    matrix = result[
        "matrix"
    ]

    country_totals = result[
        "country_totals"
    ]

    subtype_totals = result[
        "subtype_totals"
    ]

    grand_total = result[
        "grand_total"
    ]

    # -----------------------------------------------------
    # 제목
    # -----------------------------------------------------

    print()
    print("=" * 120)

    if title:

        print(
            title
        )

    else:

        print(
            "WAHIS OUTBREAK STATISTICS"
        )

    print("=" * 120)

    # -----------------------------------------------------
    # 조회 결과 없음
    # -----------------------------------------------------

    if not countries:

        print(
            "조회 결과가 없습니다."
        )

        print(
            "=" * 120
        )

        return

    # -----------------------------------------------------
    # Header
    # -----------------------------------------------------

    header = (
        ["Country"]
        + subtypes
        + ["Total"]
    )

    print(
        " | ".join(
            f"{column:>15}"
            for column in header
        )
    )

    print(
        "-" * 120
    )

    # -----------------------------------------------------
    # 국가별 데이터
    # -----------------------------------------------------

    for country in countries:

        values = [
            country
        ]

        for subtype in subtypes:

            count = (
                matrix
                .get(
                    country,
                    {}
                )
                .get(
                    subtype,
                    0
                )
            )

            values.append(
                str(count)
            )

        values.append(
            str(
                country_totals[
                    country
                ]
            )
        )

        print(
            " | ".join(
                f"{value:>15}"
                for value in values
            )
        )

    print(
        "-" * 120
    )

    # -----------------------------------------------------
    # TOTAL
    # -----------------------------------------------------

    total_values = [
        "TOTAL"
    ]

    for subtype in subtypes:

        total_values.append(
            str(
                subtype_totals[
                    subtype
                ]
            )
        )

    total_values.append(
        str(
            grand_total
        )
    )

    print(
        " | ".join(
            f"{value:>15}"
            for value in total_values
        )
    )

    print(
        "=" * 120
    )


# =========================================================
# 단독 실행 테스트
# =========================================================

if __name__ == "__main__":

    print()
    print(
        "HPAI 가금 / 가금 외 "
        "2025년 발생건수 테스트"
    )
    print()

    # -----------------------------------------------------
    # HPAI 두 종류 조회
    # -----------------------------------------------------

    hpai_rows = (
        get_hpai_outbreak_stats(
            start_date="2025-01-01",
            end_date="2025-12-31",
        )
    )

    # -----------------------------------------------------
    # 가금
    # -----------------------------------------------------

    poultry_result = build_matrix(
        hpai_rows[
            "poultry"
        ]
    )

    print(
        "가금 국가 × subtype "
        f"조합 수: "
        f"{len(hpai_rows['poultry'])}"
    )

    print(
        "가금 국가 수: "
        f"{len(poultry_result['countries'])}"
    )

    print(
        "가금 subtype 수: "
        f"{len(poultry_result['subtypes'])}"
    )

    print(
        "가금 총 발생건수: "
        f"{poultry_result['grand_total']}"
    )

    print_matrix(
        poultry_result,
        title=(
            "HPAI - 가금 (Poultry)"
        ),
    )

    # -----------------------------------------------------
    # 가금 외
    # -----------------------------------------------------

    non_poultry_result = build_matrix(
        hpai_rows[
            "non_poultry"
        ]
    )

    print(
        "가금 외 국가 × subtype "
        f"조합 수: "
        f"{len(hpai_rows['non_poultry'])}"
    )

    print(
        "가금 외 국가 수: "
        f"{len(non_poultry_result['countries'])}"
    )

    print(
        "가금 외 subtype 수: "
        f"{len(non_poultry_result['subtypes'])}"
    )

    print(
        "가금 외 총 발생건수: "
        f"{non_poultry_result['grand_total']}"
    )

    print_matrix(
        non_poultry_result,
        title=(
            "HPAI - 가금 외 "
            "(Non-poultry including wild birds)"
        ),
    )