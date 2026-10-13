import os
import sys

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database.apqa_query_db import get_apqa_snapshot


COUNTRY_MAP = {
    "United States of America": "미국",
    "United States": "미국",
    "United Kingdom": "영국",
    "Germany": "독일",
    "France": "프랑스",
    "Italy": "이탈리아",
    "Spain": "스페인",
    "Poland": "폴란드",
    "Hungary": "헝가리",
    "Denmark": "덴마크",
    "Sweden": "스웨덴",
    "Finland": "핀란드",
    "Slovakia": "슬로바키아",
    "Lithuania": "리투아니아",
    "Canada": "캐나다",
    "Australia": "호주",
    "Japan": "일본",
    "Philippines": "필리핀",
    "Chile": "칠레",
    "Brazil": "브라질",
    "Netherlands": "네덜란드",
    "Belgium": "벨기에",
    "Austria": "오스트리아",
    "Ireland": "아일랜드",
    "New Zealand": "뉴질랜드",
    "Thailand": "태국",
    "Vietnam": "베트남",
    "China": "중국",
    "Republic of Korea": "한국",
    "South Korea": "한국",
    "Czech Republic": "체코",
    "Czechia": "체코",
}


def normalize_disease(disease):
    value = str(disease or "").lower().strip()

    if (
        "highly pathogenic avian influenza" in value
        or "high pathogenicity avian influenza" in value
        or "hpai" in value
    ):
        return "HPAI"

    if "african swine fever" in value:
        return "ASF"

    if "foot and mouth disease" in value or "foot-and-mouth disease" in value:
        return "FMD"

    if "lumpy skin disease" in value:
        return "LSD"

    return None


PRODUCT_KEYWORDS = {
    "HPAI": ("가금", "닭", "오리", "계란", "식용란", "타조"),
    "ASF": ("돼지", "돈육", "돼지고기"),
    "FMD": ("소", "쇠고기", "우육", "돼지", "돈육", "돼지고기"),
    "LSD": ("소", "쇠고기", "우육"),
}



import re


def relevant_product(product, disease_code):
    """
    품목 설명 전체가 아닌 품목 제목을 기준으로
    질병 관련성을 판단한다.
    """

    value = str(product or "").strip()

    # 긴 부가 설명 제거
    title = re.split(r"\s+-\s+|\s+\d+\)", value, maxsplit=1)[0]
    title = re.sub(r"\s+", "", title)

    product_keywords = {
        "HPAI": (
            "가금류", "가금육", "식용란",
            "타조", "가금이외의조류", "야생조류"
        ),
        "ASF": (
            "돼지", "돈육", "돼지고기"
        ),
        "FMD": (
            "소", "쇠고기", "우육",
            "돼지", "돈육", "돼지고기"
        ),
        "LSD": (
            "소", "쇠고기", "우육"
        )
    }

    # BSE 관련 품목은 이번 질병 매칭에서 제외
    if "소해면상뇌증" in title or "BSE" in title.upper():
        return False

    return any(
        keyword in title
        for keyword in product_keywords.get(disease_code, ())
    )



def analyze_apqa(event, snapshot=None):
    country_en = str(event.get("country") or "").strip()
    disease = event.get("disease")

    country_kr = COUNTRY_MAP.get(country_en)
    disease_code = normalize_disease(disease)

    def result(priority, status, **kwargs):
        return {
            "priority": priority,
            "status": status,
            "country_kr": country_kr,
            "disease_code": disease_code,
            "products": [],
            "restrictions": [],
            **kwargs
        }

    if not country_kr or not disease_code:
        return result(
            "UNKNOWN",
            "국가명 또는 질병명 매칭 확인 필요"
        )

    if snapshot is None:
        snapshot = get_apqa_snapshot()

    if (
        snapshot["last_sync"] is None
        or snapshot["age_hours"] is None
        or snapshot["age_hours"] > 48
    ):
        return result(
            "UNKNOWN",
            "APQA 최신 데이터 확인 필요"
        )

    permissions = [
        row for row in snapshot["permissions"]
        if row["country"] == country_kr
        and relevant_product(row["product"], disease_code)
    ]

    restrictions = [
        row for row in snapshot["restrictions"]
        if row["country"] == country_kr
        and row["disease_code"] == disease_code
        and relevant_product(row["product"], disease_code)
    ]

    products = sorted({
        row["product"] for row in permissions
    })

    common = {
        "products": products,
        "restrictions": restrictions
    }

    if any(r["status"] == "REVIEW" for r in restrictions):
        return result(
            "UNKNOWN",
            "수입제한 조치 변경 여부 확인 필요",
            **common
        )

    if not permissions:
        return result(
            "NORMAL",
            "관련 품목의 수입허용 정보 미확인",
            **common
        )

    if any(
        r["status"] == "ACTIVE" and r["scope"] == "PARTIAL"
        for r in restrictions
    ):
        return result(
            "CAUTION",
            "일부 지역 수입제한 — 발생 지역 확인 필요",
            **common
        )

    if any(
        r["status"] == "ACTIVE" and r["scope"] == "FULL"
        for r in restrictions
    ):
        return result(
            "RESTRICTED",
            "해당 질병 관련 품목 전 지역 수입제한 조치 확인",
            **common
        )


    return result(
        "HIGH",
        "관련 수입허용 품목 존재, 해당 질병 제한 미확인",
        **common
    )


if __name__ == "__main__":
    example = {
        "country": "United Kingdom",
        "disease": "Highly pathogenic avian influenza"
    }

    result = analyze_apqa(example)

    print("국가:", result["country_kr"])
    print("질병:", result["disease_code"])
    print("중요도:", result["priority"])
    print("상태:", result["status"])
    print("수입허용 품목:", result["products"])
    print("제한 조치:", len(result["restrictions"]))
