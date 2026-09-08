import os
import requests
from dotenv import load_dotenv
from datetime import datetime


load_dotenv()


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


def format_submission_date(date_string):
    """
    WAHIS 날짜를 보기 좋은 형태로 변환한다.

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

    except ValueError:
        return date_string


def send_new_report_alert(event):
    """
    신규 WAHIS 리포트를 Slack으로 알린다.
    """

    report_id = event["reportId"]
    event_id = event["eventId"]
    country = event["country"]
    disease = event["disease"]

    submission_date = format_submission_date(
        event.get("submissionDate")
    )

    reason = event.get("reason") or "-"

    event_status = event.get("eventStatus") or "-"
    report_type = event.get("reportType") or "-"
    report_status = event.get("reportStatus") or "-"

    # WAHIS 상세 페이지
    wahis_url = (
        "https://wahis.woah.org/"
        f"#/in-review/{event_id}"
        f"?reportId={report_id}"
        "&fromPage=event-dashboard-url"
    )

    blocks = [

        # 제목
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚨 WAHIS 신규 리포트"
            }
        },

        # 구분선
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

        # 제출일 / 사유
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*🕐 제출일*\n{submission_date}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*⚠️ 사유*\n{reason}"
                }
            ]
        },

        # 상태 정보
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Event Status*\n{event_status}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Report Type*\n{report_type}"
                }
            ]
        },

        # 버튼
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

    send_slack_message(
        blocks=blocks,
        text=f"🚨 WAHIS 신규 리포트 - {country} / {disease}"
    )