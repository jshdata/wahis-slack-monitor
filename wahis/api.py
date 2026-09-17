import requests
import time


URL = "https://wahis.woah.org/api/v1/pi/event/filtered-list?language=en"


# ---------------------------------------------------------
# 모니터링 대상 질병
# ---------------------------------------------------------
# HPAI : Highly Pathogenic Avian Influenza
# ASF  : African Swine Fever
# LSD  : Lumpy Skin Disease
# FMD  : Foot and Mouth Disease

DISEASES = {
    "HPAI": 668,
    "ASF": 55,
    "LSD": 769,
    "FMD": 437
}


def get_events(page_number=0, page_size=10):
    """
    WAHIS에서 특정 페이지의 이벤트 데이터를 가져온다.

    모니터링 대상:
    - HPAI
    - ASF
    - LSD
    - FMD
    """

    payload = {
        "eventIds": [],
        "reportIds": [],
        "countries": [],

        # HPAI + ASF + LSD + FMD
        "firstDiseases": list(DISEASES.values()),

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
    운영용:
    WAHIS의 최신 데이터를 지정한 페이지 수만큼 가져온다.

    기본값:
    - 3페이지
    - 페이지당 10건
    - 총 최대 30건

    현재 대상:
    - HPAI
    - ASF
    - LSD
    - FMD
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

                events = data.get("list", [])

                all_events.extend(events)

                print(
                    f"→ {len(events)}건 수집"
                )

                break

            except requests.exceptions.RequestException as e:

                print("요청 실패:", e)
                print("5초 후 다시 시도합니다...")

                time.sleep(5)

        # WAHIS 서버에 너무 빠르게 요청하지 않도록 대기
        if page < page_count - 1:
            time.sleep(2)

    print()
    print(
        f"최신 데이터 수집 완료: "
        f"{len(all_events)}건"
    )

    return all_events


def get_all_events(page_size=10):
    """
    초기 적재용:
    HPAI + ASF + LSD + FMD의
    WAHIS 전체 데이터를 마지막 페이지까지 수집한다.

    Slack 알림용이 아니라
    DB 초기 데이터 구축에 사용한다.
    """

    all_events = []
    page_number = 0
    total_size = None

    while True:

        while True:
            try:

                print(
                    f"{page_number + 1} 페이지 수집 중..."
                )

                data = get_events(
                    page_number=page_number,
                    page_size=page_size
                )

                break

            except requests.exceptions.RequestException as e:

                print("요청 실패:", e)
                print("5초 후 다시 시도합니다...")

                time.sleep(5)

        events = data.get("list", [])

        # 첫 페이지에서 전체 데이터 수 확인
        if total_size is None:

            total_size = data.get("totalSize", 0)

            print(
                f"전체 데이터 수: {total_size}건"
            )

        all_events.extend(events)

        print(
            f"→ {len(events)}건 수집 "
            f"(누적 {len(all_events)}/{total_size})"
        )

        # 전체 데이터 수집 완료
        if len(all_events) >= total_size:
            break

        # API가 빈 페이지를 반환할 경우
        # 무한 루프 방지
        if not events:

            print(
                "더 이상 데이터가 없어 "
                "수집을 종료합니다."
            )

            break

        page_number += 1

        # 서버에 너무 빠르게 요청하지 않도록 대기
        time.sleep(1)

    print()
    print("=" * 50)
    print(
        f"전체 데이터 수집 완료: "
        f"{len(all_events)}건"
    )
    print("=" * 50)

    return all_events


if __name__ == "__main__":

    print("=" * 50)
    print("WAHIS 4대 질병 API 테스트")
    print("=" * 50)

    print("모니터링 대상:")

    for disease_name, disease_id in DISEASES.items():

        print(
            f"- {disease_name}: "
            f"WAHIS ID {disease_id}"
        )

    print()
    print("=" * 50)
    print()

    # 테스트 시 최신 3페이지(최대 30건) 확인
    events = get_latest_events(
        page_count=3,
        page_size=10
    )

    print()
    print("=" * 50)
    print("최근 데이터 확인")
    print("=" * 50)

    for event in events:

        print(
            f"report_id={event.get('reportId')} | "
            f"country={event.get('country')} | "
            f"disease={event.get('disease')} | "
            f"submission={event.get('submissionDate')}"
        )