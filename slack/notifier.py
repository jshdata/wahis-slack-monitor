# slack/notifier.py

import os
import requests
from dotenv import load_dotenv
from datetime import datetime
from database.report_alert_details import get_report_alert_details


load_dotenv()


# =========================================================
# Slack 메시지 전송
# =========================================================

def send_slack_message(blocks, text="WAHIS 신규 리포트"):
    """
    Slack Incoming Webhook으로 Block Kit 메시지를 전송한다.
    """

    webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    if not webhook_url:
        raise ValueError(
            "SLACK_WEBHOOK_URL이 .env에 설정되어 있지 않습니다."
        )

    payload = {
        "text": text,
        "blocks": blocks
    }

    response = requests.post(
        webhook_url,
        json=payload,
        timeout=10
    )

    response.raise_for_status()

    print("Slack 알림 전송 성공")


# =========================================================
# 날짜 포맷
# =========================================================

def format_submission_date(date_string):
    """
    WAHIS submissionDate를 보기 좋은 형태로 변환한다.

    예:
    2026-09-07T15:38:46.521+00:00
    ->
    2026-09-07 15:38:46 UTC
    """

    if not date_string:
        return "-"

    try:
        dt = datetime.fromisoformat(date_string)

        return dt.strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    except (ValueError, TypeError):
        return str(date_string)


# =========================================================
# WAHIS Reason 한글 표시
# =========================================================

def get_reason_label(reason):
    """
    WAHIS에서 제공하는 Reason을
    Slack에서 읽기 쉽게 표시한다.

    판정을 새로 수행하는 것이 아니라
    WAHIS가 제공한 값을 번역해서 보여준다.
    """

    if not reason:
        return "-"

    reason_lower = reason.lower().strip()

    if "first occurrence in the country" in reason_lower:
        return "🆕 국가/지역 내 첫 발생"

    if "first occurrence in a zone" in reason_lower:
        return "🆕 특정 구역 또는 구획 내 첫 발생"

    if "recurrence of an eradicated disease" in reason_lower:
        return "⚠️ 근절 후 재발"

    if "new strain in the country" in reason_lower:
        return "🧬 국가/지역 내 새로운 유형 발생"

    return reason


# =========================================================
# 신규 WAHIS Report 알림
# =========================================================

def send_new_report_alert(event):
    """
    신규 WAHIS Report를 Slack으로 알린다.

    모든 신규 Report에 대해 알림을 전송한다.

    첫 발생 / 재발 등의 정보는
    자체적으로 판정하지 않고
    WAHIS의 reason 값을 그대로 활용한다.
    """

    report_id = event["reportId"]
    event_id = event["eventId"]
    country = event["country"]
    disease = event["disease"]
    details = get_report_alert_details(event)

    submission_date = format_submission_date(
        event.get("submissionDate")
    )

    reason = event.get("reason") or "-"

    reason_label = get_reason_label(reason)

    event_status = event.get("eventStatus") or "-"
    report_type = event.get("reportType") or "-"

    # -----------------------------------------------------
    # WAHIS 상세 페이지
    # -----------------------------------------------------

    wahis_url = (
        "https://wahis.woah.org/"
        f"#/in-review/{event_id}"
        f"?reportId={report_id}"
        "&fromPage=event-dashboard-url"
    )


    # -----------------------------------------------------
    # APQA 수입 관련 정보 조회
    # -----------------------------------------------------

    try:
        from apqa.matcher import analyze_apqa

        apqa_result = analyze_apqa(event)

    except Exception as e:
        print(f"APQA 매칭 오류: {e}")

        apqa_result = {
            "priority": "UNKNOWN",
            "status": "APQA 정보 조회 실패",
            "country_kr": None,
            "disease_code": None,
            "products": [],
            "restrictions": []
        }

    priority = apqa_result["priority"]

    priority_labels = {
        "HIGH": "🚨 수입 관련 우선 검토",
        "CAUTION": "⚠️ 일부 지역 수입제한 — 추가 확인",
        "RESTRICTED": "🛑 전 지역 수입제한 조치 확인",
        "NORMAL": "📋 일반 WAHIS 신규 리포트",
        "UNKNOWN": "❓ APQA 정보 확인 필요"
    }

    alert_title = priority_labels.get(
        priority,
        "🚨 WAHIS 신규 리포트"
    )

    products = apqa_result.get("products", [])

    product_text = (
        "\n".join(f"• {p}" for p in products[:5])
        if products
        else "관련 수입허용 품목 미확인"
    )

    apqa_text = (
        "*🇰🇷 APQA 수입 관련 정보*\n"
        f"*국가:* {apqa_result.get('country_kr') or '확인 필요'}\n"
        f"*질병 코드:* {apqa_result.get('disease_code') or '확인 필요'}\n"
        f"*수입허용 관련 품목:*\n{product_text}\n"
        f"*수입제한 상태:* {apqa_result.get('status')}\n"
        f"*알림 중요도:* {priority}"
    )


    # -----------------------------------------------------
    # Slack Block Kit
    # -----------------------------------------------------

    blocks = [

        # 제목
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": alert_title
            }
        },

        {
            "type": "divider"
        },

        # 국가 / 질병
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*🌍 국가*\n{country}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*🦠 질병*\n{disease}"
                }
            ]
        },

        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*혈청형·아형:* {details['subtype']}\n"
                    f"*사육·야생 구분:* {details['animal_category']}\n"
                    f"*축종:* {details['species']}\n"
                    "_축종·구분은 이번 보고로 갱신된 발생지 중 확인된 자료 기준_"
                )
            }
        },

        # WAHIS 발생 사유
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*⚠️ 발생 사유*\n"
                    f"{reason_label}"
                )
            }
        },

        # WAHIS 원문
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"WAHIS Reason: {reason}"
                }
            ]
        },

        # Report / Event
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*📄 Report ID*\n`{report_id}`"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*🔎 Event ID*\n`{event_id}`"
                }
            ]
        },

        # 제출일
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "*🕐 제출일*\n"
                        f"{submission_date}"
                    )
                },
                {
                    "type": "mrkdwn",
                    "text": (
                        "*📋 Report Type*\n"
                        f"{report_type}"
                    )
                }
            ]
        },

        # Event 상태
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Event Status*\n"
                    f"{event_status}"
                )
            }
        },

        # WAHIS 상세보기
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "WAHIS에서 상세보기"
                    },
                    "url": wahis_url,
                    "action_id": "view_wahis_report"
                }
            ]
        }

    ]


    # -----------------------------------------------------
    # APQA 정보를 WAHIS 상세보기 버튼 바로 위에 추가
    # -----------------------------------------------------

    apqa_blocks = [
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": apqa_text
            }
        }
    ]

    # 기존 마지막 블록은 WAHIS 상세보기 버튼
    blocks[-1:-1] = apqa_blocks


    send_slack_message(
        blocks=blocks,
        text=(
            f"{alert_title} - "
            f"{country} / {disease}\n"
            f"혈청형·아형: {details['subtype']} | "
            f"사육·야생: {details['animal_category']}\n"
            f"축종: {details['species']}"
        )
    )
