
import requests
from bs4 import BeautifulSoup


APQA_URL = (
    "https://www.apqa.go.kr/livestock/clean/"
    "listwebQiaCom.do"
)

PARAMS = {
    "type": "91_103xxtFN",
    "clear": "1"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def fetch_apqa_html():
    """APQA 공식 사이트에서 HTML을 가져옵니다."""

    response = requests.get(
        APQA_URL,
        params=PARAMS,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()
    response.encoding = response.apparent_encoding

    return response.text


def get_apqa_tables():
    """수입허용국 및 수입금지 조치 테이블을 가져옵니다."""

    html = fetch_apqa_html()
    soup = BeautifulSoup(html, "html.parser")

    permission_tables = soup.select("table.tbl_orange")
    restriction_tables = soup.select("table.tbl_orange2")

    # 사이트 구조 변경이나 비정상 응답 방지
    if len(permission_tables) != 3:
        raise ValueError(
            f"수입허용 테이블 개수 오류: {len(permission_tables)}"
        )

    if len(restriction_tables) != 3:
        raise ValueError(
            f"수입금지 테이블 개수 오류: {len(restriction_tables)}"
        )

    return permission_tables, restriction_tables


if __name__ == "__main__":

    permission_tables, restriction_tables = get_apqa_tables()

    print("APQA 데이터 수집 성공")
    print("수입허용 테이블:", len(permission_tables))
    print("수입금지 테이블:", len(restriction_tables))

    for i, table in enumerate(permission_tables, start=1):
        print(
            f"수입허용 테이블 {i}:",
            len(table.select("tbody tr")),
            "개 행"
        )

    for i, table in enumerate(restriction_tables, start=1):
        print(
            f"수입금지 테이블 {i}:",
            len(table.select("tbody tr")),
            "개 행"
        )
