
import re
import json
from datetime import datetime

try:
    from apqa.scraper import get_apqa_tables
except ModuleNotFoundError:
    from scraper import get_apqa_tables


DISEASE_CODES = ["HPAI", "ASF", "FMD_LSD"]


def clean_text(value):
    """줄바꿈과 불필요한 공백 정리"""
    return re.sub(r"\s+", " ", value or "").strip()


def parse_date(value):
    """2026.10.7. -> 2026-10-07"""
    value = clean_text(value)

    if not value:
        return None

    match = re.search(
        r"(\d{4})\.(\d{1,2})\.(\d{1,2})",
        value
    )

    if not match:
        return None

    year, month, day = map(int, match.groups())

    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(f"잘못된 날짜: {value}")


def split_countries(value):
    """
    쉼표로 구분된 국가 목록 분리.
    괄호 내부 쉼표는 분리하지 않음.
    """
    countries = []
    buffer = []
    depth = 0

    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)

        if char == "," and depth == 0:
            item = clean_text("".join(buffer))

            if item:
                countries.append(item)

            buffer = []
        else:
            buffer.append(char)

    item = clean_text("".join(buffer))

    if item:
        countries.append(item)

    return countries


def parse_permissions(tables):
    """수입허용국 테이블 정규화"""

    categories = [
        "ANIMAL",
        "MEAT",
        "OTHER_PRODUCT"
    ]

    records = []

    for category, table in zip(categories, tables):
        for row in table.select("tbody tr"):
            cells = row.find_all(
                ["th", "td"],
                recursive=False
            )

            if len(cells) < 2:
                continue

            product = clean_text(
                cells[0].get_text(" ", strip=True)
            )

            country_text = clean_text(
                cells[1].get_text(" ", strip=True)
            )

            for country_entry in split_countries(country_text):
                # 조건이 포함된 국가명은 원문을 보존
                match = re.match(
                    r"^([^(*]+)",
                    country_entry
                )

                country = (
                    match.group(1).strip()
                    if match else country_entry
                )

                records.append({
                    "category": category,
                    "product": product,
                    "country": country,
                    "country_raw": country_entry
                })

    return records


def parse_restrictions(tables):
    """수입금지 조치 테이블 정규화"""

    records = []

    for disease_group, table in zip(DISEASE_CODES, tables):

        current_product = None

        for row in table.select("tbody tr"):
            cells = row.find_all(
                ["th", "td"],
                recursive=False
            )

            if not cells:
                continue

            values = [
                clean_text(cell.get_text(" ", strip=True))
                for cell in cells
            ]

            # 품목 구분 행
            if len(values) == 1:
                if values[0]:
                    current_product = values[0]
                continue

            # 국가별 조치 행
            if len(values) < 5:
                raise ValueError(
                    f"예상하지 못한 제한 행: {values}"
                )

            if not current_product:
                raise ValueError(
                    f"품목 정보 없는 제한 행: {values}"
                )

            country_raw = values[0]
            scope_raw = values[1]
            effective_date = parse_date(values[2])
            lifted_date = parse_date(values[4])

            if not country_raw:
                continue

            if scope_raw == "전체":
                scope = "FULL"
            elif scope_raw == "일부지역":
                scope = "PARTIAL"
            else:
                raise ValueError(
                    f"알 수 없는 제한 범위: {scope_raw}"
                )

            country = re.sub(
                r"\s*\([^)]*\)",
                "",
                country_raw
            ).strip()

            disease_list = (
                ["FMD", "LSD"]
                if disease_group == "FMD_LSD"
                else [disease_group]
            )

            for disease_code in disease_list:
                records.append({
                    "disease_code": disease_code,
                    "source_disease_group": disease_group,
                    "product": current_product,
                    "country": country,
                    "country_raw": country_raw,
                    "scope": scope,
                    "effective_date": effective_date,
                    "lifted_date": lifted_date
                })

    return records


def get_apqa_data():
    """APQA 수집 및 정규화 실행"""

    permission_tables, restriction_tables = get_apqa_tables()

    permissions = parse_permissions(permission_tables)
    restrictions = parse_restrictions(restriction_tables)

    return {
        "permissions": permissions,
        "restrictions": restrictions
    }


if __name__ == "__main__":
    data = get_apqa_data()

    print("\n=== APQA 데이터 정규화 완료 ===")
    print("수입허용 국가-품목 레코드:", len(data["permissions"]))
    print("수입금지 조치 레코드:", len(data["restrictions"]))

    print("\n=== 수입금지 조치 전체 ===")
    print(
        json.dumps(
            data["restrictions"],
            ensure_ascii=False,
            indent=2
        )
    )
