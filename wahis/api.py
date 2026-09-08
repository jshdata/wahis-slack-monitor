import requests
import time


URL = "https://wahis.woah.org/api/v1/pi/event/filtered-list?language=en"


def get_events(page_number=0, page_size=10):
    """
    WAHIS에서 특정 페이지의 이벤트 데이터를 가져온다.
    """

    payload = {
        "eventIds": [],
        "reportIds": [],
        "countries": [],
        "firstDiseases": [668],
        "secondDiseases": [],
        "animalTypes": [],
        "eventStartDate": None,
        "eventStatuses": [],
        "pageNumber": page_number,
        "pageSize": page_size,
        "reasons": [],
        "reportStatuses": [],
        "reportTypes": [],
        "sortColumn": "submissionDate",
        "sortOrder": "desc",
        "submissionDate": None,
        "typeStatuses": []
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    response = requests.post(
        URL,
        headers=headers,
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


def get_latest_events(page_count=3, page_size=10):
    """
    WAHIS의 최신 데이터를 지정한 페이지 수만큼 가져온다.

    기본값:
    - 3페이지
    - 페이지당 10건
    - 총 최대 30건
    """

    all_events = []

    for page in range(page_count):

        while True:
            try:
                print(
                    f"최신 데이터 "
                    f"{page + 1}/{page_count} 페이지 수집 중..."
                )

                data = get_events(
                    page_number=page,
                    page_size=page_size
                )

                events = data["list"]

                all_events.extend(events)

                print(
                    f"→ {len(events)}건 수집"
                )

                break

            except requests.exceptions.RequestException as e:

                print("요청 실패:", e)
                print("5초 후 다시 시도합니다...")

                time.sleep(5)

        # 페이지 사이 잠시 대기
        if page < page_count - 1:
            time.sleep(2)

    print()
    print(f"최신 데이터 수집 완료: {len(all_events)}건")

    return all_events


if __name__ == "__main__":

    events = get_latest_events()

    print()
    print("=" * 50)
    print("최근 데이터 확인")
    print("=" * 50)

    for event in events:
        print(
            f"report_id={event['reportId']} | "
            f"country={event['country']} | "
            f"disease={event['disease']} | "
            f"submission={event['submissionDate']}"
        )