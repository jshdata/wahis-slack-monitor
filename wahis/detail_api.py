import requests


BASE_URL = (
    "https://wahis.woah.org/api/v1/pi/review/report/"
)


def get_report_detail(report_id):
    """
    WAHIS 특정 report_id의 상세정보를 가져온다.
    """

    url = (
        f"{BASE_URL}{report_id}"
        f"/all-information?language=en"
    )

    headers = {
        "Accept": "application/json"
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


if __name__ == "__main__":

    # 테스트용 Report ID
    report_id = 185953

    print("=" * 50)
    print(f"WAHIS 상세정보 조회: {report_id}")
    print("=" * 50)

    data = get_report_detail(report_id)

    print()
    print("[Event]")
    print("eventId:", data["event"]["eventId"])
    print(
        "country:",
        data["event"]["country"]["name"]
    )
    print(
        "disease:",
        data["event"]["disease"]["name"]
    )

    subtype = data["event"].get("subType")

    if subtype:
        print(
            "subtype:",
            subtype["disease"]["name"]
        )

    print()
    print("[Report]")
    print(
        "reportId:",
        data["report"]["reportId"]
    )
    print(
        "reportNumber:",
        data["report"]["reportNumber"]
    )

    print()
    print("[Outbreaks]")
    print(
        "outbreak count:",
        len(data.get("outbreaks", []))
    )

    print()
    print("[Quantitative Data]")

    quantitative = data.get(
        "quantitativeData"
    ) or {}

    print("news:")

    for item in quantitative.get("news", []):
        print(
            item.get("speciesName"),
            "| susceptible:", item.get("susceptible"),
            "| cases:", item.get("cases"),
            "| deaths:", item.get("deaths"),
            "| killed:", item.get("killed")
        )

    print()

    print("totals:")

    for item in quantitative.get("totals", []):
        print(
            item.get("speciesName"),
            "| susceptible:", item.get("susceptible"),
            "| cases:", item.get("cases"),
            "| deaths:", item.get("deaths"),
            "| killed:", item.get("killed")
        )