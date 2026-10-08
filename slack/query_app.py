import os
import json
from datetime import datetime

from dotenv import load_dotenv

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# 기존 /wahis 조회 기능
from database.query_db import (
    search_reports,
    get_countries,
    db_utc_to_kst,
)

# /wahis-stats 통계 기능
from database.stats_db import (
    get_outbreak_stats,
    get_hpai_outbreak_stats,
    get_outbreak_duration_stats,
    get_outbreak_events,
    get_gap_days,
    build_matrix,
)


# =========================================================
# 환경변수
# =========================================================
load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

if not SLACK_BOT_TOKEN:
    raise ValueError(
        "SLACK_BOT_TOKEN이 .env에 설정되어 있지 않습니다."
    )

if not SLACK_APP_TOKEN:
    raise ValueError(
        "SLACK_APP_TOKEN이 .env에 설정되어 있지 않습니다."
    )


# =========================================================
# Slack App
# =========================================================
app = App(
    token=SLACK_BOT_TOKEN
)


# =========================================================
# 기본 옵션
# =========================================================
REGION_OPTIONS = [
    {
        "text": {
            "type": "plain_text",
            "text": "전체",
        },
        "value": "all",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "아시아",
        },
        "value": "Asia",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "유럽",
        },
        "value": "Europe",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "아프리카",
        },
        "value": "Africa",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "기타",
        },
        "value": "Other",
    },
]


ANIMAL_OPTIONS = [
    {
        "text": {
            "type": "plain_text",
            "text": "전체",
        },
        "value": "all",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "사육",
        },
        "value": "domestic",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "야생",
        },
        "value": "wild",
    },
]


DISEASE_OPTIONS = [
    {
        "text": {
            "type": "plain_text",
            "text": "전체",
        },
        "value": "all",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "HPAI",
        },
        "value": "HPAI",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "ASF",
        },
        "value": "ASF",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "FMD",
        },
        "value": "FMD",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "LSD",
        },
        "value": "LSD",
    },
]

# =========================================================
# 국가 옵션 생성
# =========================================================
def build_country_options(region=None):
    """
    선택된 권역에 맞는 국가 옵션 생성

    region:
        None   -> 전체 상태
        Asia
        Europe
        Africa
        Other
    """

    # 권역 전체일 때는 국가도 전체만 표시
    if region is None:
        return [
            {
                "text": {
                    "type": "plain_text",
                    "text": "전체",
                },
                "value": "all",
            }
        ]

    countries = get_countries(region)

    options = [
        {
            "text": {
                "type": "plain_text",
                "text": "전체",
            },
            "value": "all",
        }
    ]

    for country in countries:
        options.append(
            {
                "text": {
                    "type": "plain_text",
                    "text": country,
                },
                "value": country,
            }
        )

    return options


# =========================================================
# 질병 표시명
# =========================================================
def get_disease_label(full_name):

    # -------------------------------------------------
    # HPAI - 가금
    # -------------------------------------------------

    if full_name.startswith(
        "High pathogenicity avian influenza"
    ):
        return "HPAI - 가금 (Poultry)"

    # -------------------------------------------------
    # HPAI - 가금 외
    # -------------------------------------------------

    if full_name.startswith(
        "Influenza A viruses of high pathogenicity"
    ):
        return (
            "HPAI - 가금 외 "
            "(Non-poultry including wild birds)"
        )

    # -------------------------------------------------
    # ASF
    # -------------------------------------------------

    if full_name.startswith(
        "African swine fever"
    ):
        return "ASF"

    # -------------------------------------------------
    # FMD
    # -------------------------------------------------

    if full_name.startswith(
        "Foot and mouth disease"
    ):
        return "FMD"

    # -------------------------------------------------
    # LSD
    # -------------------------------------------------

    if full_name.startswith(
        "Lumpy skin disease"
    ):
        return "LSD"

    return full_name


# =========================================================
# Modal 생성
# =========================================================
def build_search_modal(
    selected_region="all",
    country_options=None,
):

    if country_options is None:
        country_options = build_country_options()

    # 현재 선택된 권역 option
    selected_region_option = next(
        (
            option
            for option in REGION_OPTIONS
            if option["value"] == selected_region
        ),
        REGION_OPTIONS[0],
    )

    return {
        "type": "modal",

        "callback_id": "wahis_search_modal",

        "title": {
            "type": "plain_text",
            "text": "WAHIS 데이터 조회",
        },

        "submit": {
            "type": "plain_text",
            "text": "조회하기",
        },

        "close": {
            "type": "plain_text",
            "text": "취소",
        },

        "blocks": [

            # ---------------------------------------------
            # 안내
            # ---------------------------------------------
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*🔎 WAHIS 질병 데이터 조회*\n"
                        "권역을 선택하면 국가 목록이 "
                        "자동으로 변경됩니다."
                    ),
                },
            },

            {
                "type": "divider",
            },

            # ---------------------------------------------
            # 권역
            # ---------------------------------------------
            {
                "type": "input",
                "block_id": "region_block",

                "dispatch_action": True,

                "label": {
                    "type": "plain_text",
                    "text": "🌏 권역",
                },

                "element": {
                    "type": "static_select",
                    "action_id": "region_select",

                    "initial_option": selected_region_option,

                    "options": REGION_OPTIONS,
                },
            },

            # ---------------------------------------------
            # 국가
            # ---------------------------------------------
            {
                "type": "input",
                "block_id": "country_block",

                "label": {
                    "type": "plain_text",
                    "text": "🏳️ 국가",
                },

                "element": {
                    "type": "static_select",
                    "action_id": "country_select",

                    "initial_option": country_options[0],

                    "options": country_options,
                },
            },

            # ---------------------------------------------
            # 사육 / 야생
            # ---------------------------------------------
            {
                "type": "input",
                "block_id": "animal_block",

                "label": {
                    "type": "plain_text",
                    "text": "🐾 사육 구분",
                },

                "element": {
                    "type": "static_select",
                    "action_id": "animal_select",

                    "initial_option": ANIMAL_OPTIONS[0],

                    "options": ANIMAL_OPTIONS,
                },
            },

            # ---------------------------------------------
            # 질병
            # ---------------------------------------------
            {
                "type": "input",
                "block_id": "disease_block",

                "label": {
                    "type": "plain_text",
                    "text": "🦠 질병",
                },

                "element": {
                    "type": "static_select",
                    "action_id": "disease_select",

                    "initial_option": DISEASE_OPTIONS[0],

                    "options": DISEASE_OPTIONS,
                },
            },
                # =====================================================
                # 시작 날짜
                # =====================================================
                {
                    "type": "input",
                    "block_id": "start_date_block",

                    "label": {
                        "type": "plain_text",
                        "text": "📅 시작 날짜",
                    },

                    "element": {
                        "type": "datepicker",
                        "action_id": "start_date_select",

                        "placeholder": {
                            "type": "plain_text",
                            "text": "시작 날짜 선택",
                        },
                    },
                },

                # =====================================================
                # 시작 시간
                # =====================================================
                {
                    "type": "input",
                    "block_id": "start_time_block",

                    "label": {
                        "type": "plain_text",
                        "text": "🕘 시작 시간 (KST)",
                    },

                    "element": {
                        "type": "timepicker",
                        "action_id": "start_time_select",

                        # 기본값: 오전 9시
                        "initial_time": "09:00",

                        "placeholder": {
                            "type": "plain_text",
                            "text": "시작 시간 선택",
                        },
                    },
                },

                # =====================================================
                # 종료 날짜
                # =====================================================
                {
                    "type": "input",
                    "block_id": "end_date_block",

                    "label": {
                        "type": "plain_text",
                        "text": "📅 종료 날짜",
                    },

                    "element": {
                        "type": "datepicker",
                        "action_id": "end_date_select",

                        "placeholder": {
                            "type": "plain_text",
                            "text": "종료 날짜 선택",
                        },
                    },
                },

                # =====================================================
                # 종료 시간
                # =====================================================
                {
                    "type": "input",
                    "block_id": "end_time_block",

                    "label": {
                        "type": "plain_text",
                        "text": "🕘 종료 시간 (KST)",
                    },

                    "element": {
                        "type": "timepicker",
                        "action_id": "end_time_select",

                        # 기본값: 오전 9시
                        "initial_time": "09:00",

                        "placeholder": {
                            "type": "plain_text",
                            "text": "종료 시간 선택",
                        },
                    },
                },

        ],
    }


# =========================================================
# /wahis
# =========================================================
@app.command("/wahis")
def handle_wahis_command(
    ack,
    body,
    client,
):

    ack()

    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_search_modal(),
    )


# =========================================================
# 권역 변경
# =========================================================
@app.action("region_select")
def handle_region_change(
    ack,
    body,
    client,
):

    ack()

    selected_region = (
        body["actions"][0]
        ["selected_option"]
        ["value"]
    )

    # ---------------------------------------------
    # 권역에 맞는 국가 목록
    # ---------------------------------------------
    if selected_region == "all":

        country_options = (
            build_country_options()
        )

    else:

        country_options = (
            build_country_options(
                selected_region
            )
        )

    # ---------------------------------------------
    # Modal 갱신
    # ---------------------------------------------
    client.views_update(
        view_id=body["view"]["id"],

        hash=body["view"]["hash"],

        view=build_search_modal(
            selected_region=selected_region,
            country_options=country_options,
        ),
    )


# =========================================================
# 조회하기
# =========================================================
@app.view("wahis_search_modal")
def handle_wahis_search(
    ack,
    body,
    view,
    client,
):

    ack()

    values = view["state"]["values"]

    # ---------------------------------------------
    # Slack 선택값
    # ---------------------------------------------
    region = (
        values["region_block"]
        ["region_select"]
        ["selected_option"]
        ["value"]
    )

    country = (
        values["country_block"]
        ["country_select"]
        ["selected_option"]
        ["value"]
    )

    animal = (
        values["animal_block"]
        ["animal_select"]
        ["selected_option"]
        ["value"]
    )

    disease = (
        values["disease_block"]
        ["disease_select"]
        ["selected_option"]
        ["value"]
    )
    # ---------------------------------------------
    # 조회 시작/종료 날짜·시간
    # ---------------------------------------------
    start_date = (
        values["start_date_block"]
        ["start_date_select"]
        ["selected_date"]
    )

    start_time = (
        values["start_time_block"]
        ["start_time_select"]
        ["selected_time"]
    )

    end_date = (
        values["end_date_block"]
        ["end_date_select"]
        ["selected_date"]
    )

    end_time = (
        values["end_time_block"]
        ["end_time_select"]
        ["selected_time"]
    )
    # KST 기준 조회시간 생성
    start_datetime = f"{start_date} {start_time}:00"
    end_datetime = f"{end_date} {end_time}:00"

    # =====================================================
    # 조회 기간 검증
    # =====================================================
    start_dt = datetime.fromisoformat(
        f"{start_date}T{start_time}"
    )

    end_dt = datetime.fromisoformat(
        f"{end_date}T{end_time}"
    )

    if start_dt >= end_dt:
        client.chat_postMessage(
            channel=body["user"]["id"],
            text=(
                "⚠️ 조회 기간을 확인해주세요.\n\n"
                "종료 날짜·시간은 시작 날짜·시간보다 "
                "뒤여야 합니다."
            ),
        )
        return

    # =====================================================
    # Slack 값 → DB 값 변환
    # =====================================================
    db_region = (
        None
        if region == "all"
        else region
    )

    db_country = (
        None
        if country == "all"
        else country
    )

    db_disease = (
        None
        if disease == "all"
        else disease
    )

    if animal == "wild":
        db_wild = True

    elif animal == "domestic":
        db_wild = False

    else:
        db_wild = None

    # =====================================================
    # 실제 DB 조회
    # =====================================================
    try:
        results = search_reports(
            region=db_region,
            country=db_country,
            wild=db_wild,
            disease=db_disease,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            limit=20,
        )

    except Exception as e:

        print(
            "WAHIS 조회 오류: "
            f"{type(e).__name__}: {e}"
        )

        client.chat_postMessage(
            channel=body["user"]["id"],
            text=(
                "❌ WAHIS 데이터 조회 중 "
                "오류가 발생했습니다.\n"
                "터미널 로그를 확인해주세요."
            ),
        )

        return

    # =====================================================
    # 조회 조건 표시
    # =====================================================
    region_label = {
        "all": "전체",
        "Asia": "아시아",
        "Europe": "유럽",
        "Africa": "아프리카",
        "Other": "기타",
    }.get(
        region,
        region,
    )

    animal_label = {
        "all": "전체",
        "domestic": "사육",
        "wild": "야생",
    }.get(
        animal,
        animal,
    )

    country_label = (
        "전체 국가"
        if country == "all"
        else country
    )

    disease_label = (
        "전체 질병"
        if disease == "all"
        else disease
    )

    condition_text = (
        f"{region_label} · "
        f"{country_label} · "
        f"{animal_label} · "
        f"{disease_label}\n"
        f"📅 {start_date} {start_time} ~ "
        f"{end_date} {end_time} KST"
    )

    # =====================================================
    # 결과 없음
    # =====================================================
    if not results:

        client.chat_postMessage(
            channel=body["user"]["id"],

            text=(
                "🔎 *WAHIS 조회 결과*\n\n"
                "*조회 조건*\n"
                f"{condition_text}\n\n"
                "조회된 Report가 없습니다."
            ),
        )

        return

    # =====================================================
    # 결과 메시지
    # =====================================================
    lines = [
        "🔎 *WAHIS 조회 결과*",
        "",
        "*조회 조건*",
        condition_text,
        "",
        f"*조회 결과: {len(results)}건*",
        "",
    ]

    for row in results:

        (
            report_id,
            event_id,
            report_country,
            report_region,
            full_disease,
            submission_date,
            report_type,
            report_status,
        ) = row

        short_disease = (
            get_disease_label(
                full_disease
            )
        )
        if submission_date:

            submission_date_kst = db_utc_to_kst(
                submission_date
            )

            date_text = (
                submission_date_kst.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                + " KST"
            )

        else:

            date_text = "-"

        wahis_url = (
            "https://wahis.woah.org/"
            f"#/in-review/{event_id}"
            f"?reportId={report_id}"
            "&fromPage=event-dashboard-url"
        )

        lines.extend(
            [
                "━━━━━━━━━━━━━━━━━━━━",
                f"🌍 *{report_country}*",
                f"🌐 권역: {report_region}",
                f"🦠 질병: `{short_disease}`",
                f"📄 Report ID: `{report_id}`",
                f"🔎 Event ID: `{event_id}`",
                f"🕒 제출일: {date_text}",
                (
                    "📌 상태: "
                    f"{report_status or '-'}"
                ),
                (
                    "📑 유형: "
                    f"{report_type or '-'}"
                ),
                (
                    f"<{wahis_url}|"
                    "WAHIS에서 상세보기>"
                ),
                "",
            ]
        )

    # =====================================================
    # 20건 제한 안내
    # =====================================================
    if len(results) == 20:

        lines.extend(
            [
                "※ 최대 20건까지 표시합니다.",
                (
                    "조건을 더 좁히면 원하는 "
                    "데이터를 쉽게 확인할 수 있습니다."
                ),
            ]
        )

    # =====================================================
    # Slack DM 전송
    # =====================================================
    client.chat_postMessage(
        channel=body["user"]["id"],
        text="\n".join(lines),
    )

# =========================================================
# /wahis-stats 옵션
# =========================================================

STATS_DISEASE_OPTIONS = [
    {
        "text": {
            "type": "plain_text",
            "text": "HPAI",
        },
        "value": "HPAI",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "ASF",
        },
        "value": "ASF",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "FMD",
        },
        "value": "FMD",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "LSD",
        },
        "value": "LSD",
    },
]


STATS_VIEW_OPTIONS = [
    {
        "text": {
            "type": "plain_text",
            "text": "국가별 총 발생건수",
        },
        "value": "country_total",
    },
    {
        "text": {
            "type": "plain_text",
            "text": "국가 × 세부질병 Matrix",
        },
        "value": "matrix",
    },
        {
        "text": {
            "type": "plain_text",
            "text": "국가별 발생 기간(일)",
        },
        "value": "duration",
    },
]


# =========================================================
# /wahis-stats Modal 생성
# =========================================================

def build_stats_modal(
    selected_region="all",
    country_options=None,
):

    if country_options is None:
        country_options = build_country_options()

    selected_region_option = next(
        (
            option
            for option in REGION_OPTIONS
            if option["value"] == selected_region
        ),
        REGION_OPTIONS[0],
    )

    return {
        "type": "modal",

        "callback_id": "wahis_stats_modal",

        "title": {
            "type": "plain_text",
            "text": "WAHIS 발생 통계",
        },

        "submit": {
            "type": "plain_text",
            "text": "조회하기",
        },

        "close": {
            "type": "plain_text",
            "text": "취소",
        },

        "blocks": [

            # ---------------------------------------------
            # 안내
            # ---------------------------------------------
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*📊 WAHIS 발생건수 통계*\n"
                        "발생일(outbreak.start_date) 기준으로 "
                        "고유 outbreak를 집계합니다."
                    ),
                },
            },

            {
                "type": "divider",
            },

            # ---------------------------------------------
            # 질병
            # ---------------------------------------------
            {
                "type": "input",
                "block_id": "stats_disease_block",

                "label": {
                    "type": "plain_text",
                    "text": "🦠 질병",
                },

                "element": {
                    "type": "static_select",
                    "action_id": "stats_disease_select",

                    "initial_option":
                        STATS_DISEASE_OPTIONS[0],

                    "options":
                        STATS_DISEASE_OPTIONS,
                },
            },

            # ---------------------------------------------
            # 권역
            # ---------------------------------------------
            {
                "type": "input",
                "block_id": "stats_region_block",

                "dispatch_action": True,

                "label": {
                    "type": "plain_text",
                    "text": "🌏 권역",
                },

                "element": {
                    "type": "static_select",
                    "action_id": "stats_region_select",

                    "initial_option":
                        selected_region_option,

                    "options":
                        REGION_OPTIONS,
                },
            },

            # ---------------------------------------------
            # 국가
            # ---------------------------------------------
            {
                "type": "input",
                "block_id": "stats_country_block",

                "label": {
                    "type": "plain_text",
                    "text": "🏳️ 국가",
                },

                "element": {
                    "type": "static_select",
                    "action_id": "stats_country_select",

                    "initial_option":
                        country_options[0],

                    "options":
                        country_options,
                },
            },

            # ---------------------------------------------
            # 시작일
            # ---------------------------------------------
            {
                "type": "input",
                "block_id": "stats_start_date_block",

                "label": {
                    "type": "plain_text",
                    "text": "📅 시작일",
                },

                "element": {
                    "type": "datepicker",
                    "action_id": "stats_start_date",

                    "placeholder": {
                        "type": "plain_text",
                        "text": "시작일 선택",
                    },
                },
            },

            # ---------------------------------------------
            # 종료일
            # ---------------------------------------------
            {
                "type": "input",
                "block_id": "stats_end_date_block",

                "label": {
                    "type": "plain_text",
                    "text": "📅 종료일",
                },

                "element": {
                    "type": "datepicker",
                    "action_id": "stats_end_date",

                    "placeholder": {
                        "type": "plain_text",
                        "text": "종료일 선택",
                    },
                },
            },

            # ---------------------------------------------
            # 조회 형태
            # ---------------------------------------------
            {
                "type": "input",
                "block_id": "stats_view_block",

                "label": {
                    "type": "plain_text",
                    "text": "📋 조회 형태",
                },

                "element": {
                    "type": "static_select",
                    "action_id": "stats_view_select",

                    "initial_option":
                        STATS_VIEW_OPTIONS[0],

                    "options":
                        STATS_VIEW_OPTIONS,
                },
            },
        ],
    }


# =========================================================
# /wahis-stats 명령어
# =========================================================

@app.command("/wahis-stats")
def handle_wahis_stats_command(
    ack,
    body,
    client,
):

    ack()

    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_stats_modal(),
    )


# =========================================================
# /wahis-stats 권역 변경
# =========================================================

@app.action("stats_region_select")
def handle_stats_region_change(
    ack,
    body,
    client,
):

    ack()

    selected_region = (
        body["actions"][0]
        ["selected_option"]
        ["value"]
    )

    print(
        f"[WAHIS-STATS] 선택된 권역: "
        f"{selected_region}"
    )

    # =====================================================
    # 권역에 따른 국가 목록 생성
    # =====================================================

    if selected_region == "all":

        country_options = (
            build_country_options()
        )

    else:

        country_options = (
            build_country_options(
                selected_region
            )
        )

    print(
        f"[WAHIS-STATS] 국가 옵션 수: "
        f"{len(country_options)}"
    )

    print(
        "[WAHIS-STATS] 국가 옵션:",
        [
            option["value"]
            for option in country_options
        ]
    )

    # =====================================================
    # Modal 업데이트
    # =====================================================

    client.views_update(
        view_id=body["view"]["id"],

        hash=body["view"]["hash"],

        view=build_stats_modal(
            selected_region=selected_region,
            country_options=country_options,
        ),
    )


# =========================================================
# 국가별 총 발생건수 메시지
# =========================================================

def build_country_total_text(
    result,
    disease,
    region_label,
    country_label,
    start_date,
    end_date,
):

    countries = result["countries"]
    totals = result["country_totals"]
    grand_total = result["grand_total"]

    lines = [
        "📊 *WAHIS 국가별 발생건수*",
        "",
        f"*질병:* {disease}",
        f"*권역:* {region_label}",
        f"*국가:* {country_label}",
        f"*발생기간:* {start_date} ~ {end_date}",
        "*기준:* outbreak.start_date",
        "",
    ]

    # ---------------------------------------------
    # 결과 없음
    # ---------------------------------------------

    if not countries:

        lines.append(
            "조회된 outbreak가 없습니다."
        )

        return "\n".join(lines)

    # ---------------------------------------------
    # 발생건수 많은 국가 순으로 정렬
    # ---------------------------------------------

    ranked = sorted(
        (
            (
                country,
                totals[country]
            )
            for country in countries
        ),
        key=lambda item: (
            -item[1],
            item[0]
        ),
    )

    # ---------------------------------------------
    # 표
    # ---------------------------------------------

    lines.append("```")

    lines.append(
        f"{'Country':<30} "
        f"{'Outbreaks':>10}"
    )

    lines.append(
        "-" * 42
    )

    for country, count in ranked:

        lines.append(
            f"{country[:30]:<30} "
            f"{count:>10,}"
        )

    lines.append(
        "-" * 42
    )

    lines.append(
        f"{'TOTAL':<30} "
        f"{grand_total:>10,}"
    )

    lines.append("```")

    return "\n".join(lines)


# =========================================================
# Matrix 메시지
# =========================================================

def build_matrix_text(
    result,
    disease,
    region_label,
    country_label,
    start_date,
    end_date,
):

    countries = result["countries"]
    subtypes = result["subtypes"]

    matrix = result["matrix"]
    country_totals = result["country_totals"]

    region_matrix = result["region_matrix"]
    region_totals = result["region_totals"]

    subtype_totals = result["subtype_totals"]
    grand_total = result["grand_total"]

    # =====================================================
    # 국가 정렬
    #
    # 발생건수 많은 국가부터
    # =====================================================

    countries = sorted(
        countries,
        key=lambda country: (
            -country_totals[country],
            country
        )
    )

    # =====================================================
    # 기본 정보
    # =====================================================

    lines = [
        "📊 *WAHIS 국가 × 세부질병 Matrix*",
        "",
        f"*질병:* {disease}",
        f"*권역:* {region_label}",
        f"*국가:* {country_label}",
        f"*발생기간:* {start_date} ~ {end_date}",
        "*기준:* outbreak.start_date",
        "",
    ]

    # =====================================================
    # 결과 없음
    # =====================================================

    if not countries:

        lines.append(
            "조회된 outbreak가 없습니다."
        )

        return "\n".join(
            lines
        )

    # =====================================================
    # 표 너비
    # =====================================================

    country_width = 20
    subtype_width = 10
    total_width = 8

    lines.append(
        "```"
    )

    # =====================================================
    # Header
    # =====================================================

    header_text = (
        f"{'Region/Country':<{country_width}}"
    )

    for subtype in subtypes:

        header_text += (
            f" "
            f"{subtype[:subtype_width]:>{subtype_width}}"
        )

    header_text += (
        f" "
        f"{'Total':>{total_width}}"
    )

    lines.append(
        header_text
    )

    lines.append(
        "-" * len(header_text)
    )

    # =====================================================
    # 권역별 합계
    # =====================================================

    region_order = [
        "Asia",
        "Europe",
        "Africa",
        "North America",
        "South America",
        "Oceania",
        "Other",
    ]

    # 페이지 분할할 때 권역 행을 구분하기 위한 표시
    lines.append(
        "[REGION_START]"
    )

    for region in region_order:

        if region not in region_matrix:
            continue

        row_text = (
            f"{region:<{country_width}}"
        )

        for subtype in subtypes:

            count = (
                region_matrix
                .get(
                    region,
                    {}
                )
                .get(
                    subtype,
                    0
                )
            )

            row_text += (
                f" "
                f"{count:>{subtype_width},}"
            )

        row_text += (
            f" "
            f"{region_totals[region]:>{total_width},}"
        )

        lines.append(
            row_text
        )

    lines.append(
        "[REGION_END]"
    )

    # =====================================================
    # 권역 / 국가 구분선
    # =====================================================

    lines.append(
        "-" * len(header_text)
    )

    # =====================================================
    # 국가별 행
    # =====================================================

    for country in countries:

        display_country = country

        if len(display_country) > country_width:

            display_country = (
                display_country[
                    :country_width - 2
                ]
                + ".."
            )

        row_text = (
            f"{display_country:<{country_width}}"
        )

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

            row_text += (
                f" "
                f"{count:>{subtype_width},}"
            )

        row_text += (
            f" "
            f"{country_totals[country]:>{total_width},}"
        )

        lines.append(
            row_text
        )

    # =====================================================
    # TOTAL
    # =====================================================

    lines.append(
        "-" * len(header_text)
    )

    total_text = (
        f"{'TOTAL':<{country_width}}"
    )

    for subtype in subtypes:

        total_text += (
            f" "
            f"{subtype_totals[subtype]:>{subtype_width},}"
        )

    total_text += (
        f" "
        f"{grand_total:>{total_width},}"
    )

    lines.append(
        total_text
    )

    lines.append(
        "```"
    )

    return "\n".join(
        lines
    )

# =========================================================
# Matrix 전용 Slack 메시지 분할 전송
# =========================================================

def post_matrix_message(
    client,
    channel,
    text,
    rows_per_page=20,
):

    lines = text.split(
        "\n"
    )

    # =====================================================
    # 조회 결과가 없는 경우
    #
    # 코드블록이 없으므로 그냥 전송
    # =====================================================

    if "```" not in lines:

        client.chat_postMessage(
            channel=channel,
            text=text,
        )

        return

    # =====================================================
    # 코드블록 위치
    # =====================================================

    code_start = lines.index(
        "```"
    )

    code_end = len(lines) - 1

    # =====================================================
    # 표 위 조회조건
    # =====================================================

    info_lines = lines[
        :code_start
    ]

    # =====================================================
    # 표 내부
    # =====================================================

    table_lines = lines[
        code_start + 1
        :code_end
    ]

    # =====================================================
    # Header
    # =====================================================

    header = table_lines[0]
    separator = table_lines[1]

    # =====================================================
    # 권역 행 위치
    # =====================================================

    region_start = table_lines.index(
        "[REGION_START]"
    )

    region_end = table_lines.index(
        "[REGION_END]"
    )

    # =====================================================
    # 권역별 합계 행
    # =====================================================

    region_rows = table_lines[
        region_start + 1
        :region_end
    ]

    # =====================================================
    # 국가별 행
    #
    # REGION_END 다음에는
    # 권역/국가 구분선이 하나 있으므로 +2
    #
    # 마지막 두 줄은
    # 구분선 + TOTAL
    # =====================================================

    country_rows = table_lines[
        region_end + 2
        :-2
    ]

    # =====================================================
    # TOTAL
    # =====================================================

    total_separator = (
        table_lines[-2]
    )

    total_row = (
        table_lines[-1]
    )

    # =====================================================
    # 국가 행 페이지 분할
    #
    # 첫 페이지에는 권역 합계가 들어가기 때문에
    # 국가 행 수를 줄여서 배치
    # =====================================================

    first_page_rows = max(
        5,
        rows_per_page - len(region_rows)
    )

    pages = []

    # -----------------------------------------------------
    # 첫 페이지
    # -----------------------------------------------------

    first_page = country_rows[
        :first_page_rows
    ]

    pages.append(
        first_page
    )

    # -----------------------------------------------------
    # 나머지 국가 행
    # -----------------------------------------------------

    remaining_rows = country_rows[
        first_page_rows:
    ]

    for i in range(
        0,
        len(remaining_rows),
        rows_per_page
    ):

        pages.append(
            remaining_rows[
                i:i + rows_per_page
            ]
        )

    # -----------------------------------------------------
    # 국가 행이 없는 경우에도
    # 최소 1페이지 생성
    # -----------------------------------------------------

    if not country_rows:

        pages = [
            []
        ]

    total_pages = len(
        pages
    )

    # =====================================================
    # 페이지별 Slack 전송
    # =====================================================

    for page_number, page_rows in enumerate(
        pages,
        start=1,
    ):

        message_lines = []

        # ---------------------------------------------
        # 페이지 번호
        # ---------------------------------------------

        if total_pages > 1:

            message_lines.extend([
                (
                    f"*결과 "
                    f"{page_number}/"
                    f"{total_pages}*"
                ),
                "",
            ])

        # ---------------------------------------------
        # 첫 페이지
        #
        # 조회조건 + 권역 합계 표시
        # ---------------------------------------------

        if page_number == 1:

            message_lines.extend(
                info_lines
            )

        # ---------------------------------------------
        # 2페이지 이후
        # ---------------------------------------------

        else:

            message_lines.extend([
                (
                    "📊 *WAHIS 국가 × "
                    "세부질병 Matrix*"
                ),
                "",
            ])

        # =================================================
        # 코드블록 시작
        # =================================================

        message_lines.extend([
            "```",
            header,
            separator,
        ])

        # =================================================
        # 권역 합계는 첫 페이지에만 표시
        # =================================================

        if page_number == 1:

            message_lines.extend(
                region_rows
            )

            # 권역 / 국가 구분
            message_lines.append(
                separator
            )

        # =================================================
        # 국가 행
        # =================================================

        message_lines.extend(
            page_rows
        )

        # =================================================
        # TOTAL은 마지막 페이지에만 표시
        # =================================================

        if page_number == total_pages:

            message_lines.extend([
                total_separator,
                total_row,
            ])

        # =================================================
        # 코드블록 종료
        # =================================================

        message_lines.append(
            "```"
        )

        # =================================================
        # Slack 전송
        # =================================================

        client.chat_postMessage(
            channel=channel,
            text="\n".join(
                message_lines
            ),
        )

# =========================================================
# 긴 Slack 메시지 분할
# =========================================================

def post_long_message(
    client,
    channel,
    text,
    max_length=3500,
):

    # ---------------------------------------------
    # 짧으면 바로 전송
    # ---------------------------------------------

    if len(text) <= max_length:

        client.chat_postMessage(
            channel=channel,
            text=text,
        )

        return

    # ---------------------------------------------
    # 줄 단위 분할
    # ---------------------------------------------

    lines = text.split("\n")

    chunks = []
    current = []

    for line in lines:

        candidate = "\n".join(
            current + [line]
        )

        if (
            current
            and len(candidate) > max_length
        ):

            chunks.append(
                "\n".join(current)
            )

            current = [line]

        else:

            current.append(line)

    if current:

        chunks.append(
            "\n".join(current)
        )

    # ---------------------------------------------
    # 여러 메시지 전송
    # ---------------------------------------------

    for index, chunk in enumerate(
        chunks,
        start=1,
    ):

        prefix = ""

        if len(chunks) > 1:

            prefix = (
                f"*결과 "
                f"{index}/{len(chunks)}*\n"
            )

        client.chat_postMessage(
            channel=channel,
            text=prefix + chunk,
        )

# =========================================================
# 국가별 발생 기간(일) 메시지
# =========================================================

def build_duration_messages(
    rows,
    disease,
    region_label,
    country_label,
    start_date,
    end_date,
    gap_days,
    rows_per_page=40,
):
    """
    국가별 발생 기간(일) 메시지 목록을 만든다.

    표가 길면 코드블록이 깨지지 않도록
    페이지마다 코드블록을 새로 연다.
    """

    period_days = (
        datetime.fromisoformat(end_date)
        - datetime.fromisoformat(start_date)
    ).days + 1

    header_lines = [
        "📅 *WAHIS 국가별 발생 기간(일)*",
        "",
        f"*질병:* {disease}",
        f"*권역:* {region_label}",
        f"*국가:* {country_label}",
        (
            f"*조회기간:* {start_date} ~ {end_date} "
            f"({period_days}일)"
        ),
        (
            "*기준:* outbreak.start_date, "
            f"발생일 간격 {gap_days}일 초과 시 별도 발생"
        ),
        "",
    ]

    if not rows:

        return [
            "\n".join(
                header_lines
                + ["조회된 outbreak가 없습니다."]
            )
        ]

    table_header = (
        f"{'Country':<26} "
        f"{'Episodes':>8} "
        f"{'Days':>6} "
        f"{'Ratio':>7}"
    )

    separator = "-" * len(table_header)

    body_rows = []

    for country, _region, episode_count, days in rows:

        days = int(days)

        ratio = days / period_days * 100

        body_rows.append(
            f"{country[:26]:<26} "
            f"{int(episode_count):>8,} "
            f"{days:>6,} "
            f"{ratio:>6.1f}%"
        )

    pages = [
        body_rows[i:i + rows_per_page]
        for i in range(
            0,
            len(body_rows),
            rows_per_page,
        )
    ]

    messages = []

    for number, page in enumerate(pages, start=1):

        lines = []

        if len(pages) > 1:

            lines += [
                f"*결과 {number}/{len(pages)}*",
                "",
            ]

        if number == 1:

            lines += header_lines

        lines += [
            "```",
            table_header,
            separator,
        ]

        lines += page

        lines.append("```")

        messages.append(
            "\n".join(lines)
        )

    return messages

# =========================================================
# Event 목록 (WAHIS 링크) 버튼 / 모달
# =========================================================

# 모달 한 페이지에 보여줄 Event 수
EVENT_PAGE_SIZE = 10

EVENT_DISEASE_LABELS = {
    "HPAI": "HPAI - 가금 (Poultry)",
    "HPAI_NON_POULTRY": (
        "HPAI - 가금 외 "
        "(Non-poultry including wild birds)"
    ),
}


def build_wahis_url(event_id, report_id):

    return (
        "https://wahis.woah.org/"
        f"#/in-review/{event_id}"
        f"?reportId={report_id}"
        "&fromPage=event-dashboard-url"
    )


def post_event_button(
    client,
    channel,
    code,
    start_date,
    end_date,
    db_region,
    db_country,
):
    """
    결과 표 아래에 'Event 목록 보기' 버튼 메시지를 보낸다.

    조회 조건은 버튼의 value에 담아 두고,
    버튼을 누르면 이 조건으로 Event 목록을 조회한다.
    """

    label = EVENT_DISEASE_LABELS.get(
        code,
        code,
    )

    value = json.dumps(
        {
            "c": code,
            "s": start_date,
            "e": end_date,
            "r": db_region or "",
            "k": db_country or "",
        },
        ensure_ascii=False,
    )

    client.chat_postMessage(
        channel=channel,
        text=f"발생 Event 목록 - {label}",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"🔗 *{label}*\n"
                        "발생 Event의 WAHIS 링크를 "
                        "확인할 수 있습니다."
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "open_event_list",
                        "text": {
                            "type": "plain_text",
                            "text": "Event 목록 보기",
                        },
                        "value": value,
                    }
                ],
            },
        ],
    )


def build_event_list_modal(params, page):
    """
    Event 목록 모달을 만든다.

    params: 버튼 value에 담긴 조회 조건
    page  : 0부터 시작하는 페이지 번호
    """

    rows = get_outbreak_events(
        disease_code=params["c"],
        start_date=params["s"],
        end_date=params["e"],
        region=params["r"] or None,
        country=params["k"] or None,
        limit=EVENT_PAGE_SIZE,
        offset=page * EVENT_PAGE_SIZE,
    )

    total = (
        int(rows[0][6])
        if rows
        else 0
    )

    total_pages = max(
        1,
        (total + EVENT_PAGE_SIZE - 1)
        // EVENT_PAGE_SIZE,
    )

    label = EVENT_DISEASE_LABELS.get(
        params["c"],
        params["c"],
    )

    country_text = (
        params["k"]
        if params["k"]
        else "전체 국가"
    )

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{label}*\n"
                    f"🏳️ {country_text}\n"
                    f"📅 {params['s']} ~ {params['e']}\n"
                    f"Event *{total}개* "
                    f"({page + 1}/{total_pages} 페이지)"
                ),
            },
        },
        {
            "type": "divider",
        },
    ]

    if not rows:

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "표시할 Event가 없습니다.",
                },
            }
        )

    for row in rows:

        (
            event_id,
            country,
            subtype,
            first_start,
            outbreak_count,
            report_id,
            _total,
        ) = row

        date_text = (
            first_start.strftime("%Y-%m-%d")
            if first_start
            else "-"
        )

        subtype_text = (
            f" · {subtype}"
            if subtype
            else ""
        )

        url = build_wahis_url(
            event_id,
            report_id,
        )

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"🌍 *{country}*{subtype_text}\n"
                        f"🕒 {date_text} 시작 · "
                        f"outbreak {int(outbreak_count)}건\n"
                        f"🔎 Event `{event_id}` · "
                        f"<{url}|WAHIS에서 보기>"
                    ),
                },
            }
        )

        blocks.append(
            {
                "type": "divider",
            }
        )

    # -------------------------------------------------
    # 이전 / 다음 버튼
    # -------------------------------------------------

    elements = []

    if page > 0:

        elements.append(
            {
                "type": "button",
                "action_id": "event_list_prev",
                "text": {
                    "type": "plain_text",
                    "text": "◀ 이전",
                },
            }
        )

    if page + 1 < total_pages:

        elements.append(
            {
                "type": "button",
                "action_id": "event_list_next",
                "text": {
                    "type": "plain_text",
                    "text": "다음 ▶",
                },
            }
        )

    if elements:

        blocks.append(
            {
                "type": "actions",
                "elements": elements,
            }
        )

    return {
        "type": "modal",

        "callback_id": "event_list_modal",

        "title": {
            "type": "plain_text",
            "text": "발생 Event 목록",
        },

        "close": {
            "type": "plain_text",
            "text": "닫기",
        },

        # 이전 / 다음 버튼이 조회 조건을 알 수 있도록 보관
        "private_metadata": json.dumps(
            {**params, "page": page},
            ensure_ascii=False,
        ),

        "blocks": blocks,
    }


def build_message_modal(text):
    """
    '불러오는 중' / 오류 안내용 간단한 모달
    """

    return {
        "type": "modal",

        "title": {
            "type": "plain_text",
            "text": "발생 Event 목록",
        },

        "close": {
            "type": "plain_text",
            "text": "닫기",
        },

        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text,
                },
            }
        ],
    }


@app.action("open_event_list")
def handle_open_event_list(
    ack,
    body,
    client,
):

    ack()

    params = json.loads(
        body["actions"][0]["value"]
    )

    # trigger_id는 3초 안에 써야 하므로
    # 먼저 '불러오는 중' 모달을 열고
    # DB 조회 후 내용을 교체한다.
    opened = client.views_open(
        trigger_id=body["trigger_id"],
        view=build_message_modal(
            "⏳ Event 목록을 불러오는 중입니다..."
        ),
    )

    view_id = opened["view"]["id"]

    try:

        view = build_event_list_modal(
            params,
            0,
        )

    except Exception as e:

        print(
            "WAHIS Event 목록 조회 오류: "
            f"{type(e).__name__}: {e}"
        )

        view = build_message_modal(
            "❌ Event 목록 조회 중 오류가 "
            "발생했습니다."
        )

    client.views_update(
        view_id=view_id,
        view=view,
    )


def change_event_page(
    body,
    client,
    delta,
):

    meta = json.loads(
        body["view"]["private_metadata"]
    )

    page = max(
        0,
        int(meta.get("page", 0)) + delta,
    )

    params = {
        key: value
        for key, value in meta.items()
        if key != "page"
    }

    try:

        view = build_event_list_modal(
            params,
            page,
        )

    except Exception as e:

        print(
            "WAHIS Event 목록 페이지 오류: "
            f"{type(e).__name__}: {e}"
        )

        view = build_message_modal(
            "❌ Event 목록 조회 중 오류가 "
            "발생했습니다."
        )

    client.views_update(
        view_id=body["view"]["id"],
        hash=body["view"]["hash"],
        view=view,
    )


@app.action("event_list_prev")
def handle_event_list_prev(
    ack,
    body,
    client,
):

    ack()

    change_event_page(
        body,
        client,
        -1,
    )


@app.action("event_list_next")
def handle_event_list_next(
    ack,
    body,
    client,
):

    ack()

    change_event_page(
        body,
        client,
        1,
    )

# =========================================================
# /wahis-stats 조회
# =========================================================

@app.view("wahis_stats_modal")
def handle_wahis_stats_search(
    ack,
    body,
    view,
    client,
):

    values = view["state"]["values"]

    # =====================================================
    # Slack 선택값
    # =====================================================

    disease = (
        values["stats_disease_block"]
        ["stats_disease_select"]
        ["selected_option"]
        ["value"]
    )

    region = (
        values["stats_region_block"]
        ["stats_region_select"]
        ["selected_option"]
        ["value"]
    )

    country = (
        values["stats_country_block"]
        ["stats_country_select"]
        ["selected_option"]
        ["value"]
    )

    start_date = (
        values["stats_start_date_block"]
        ["stats_start_date"]
        ["selected_date"]
    )

    end_date = (
        values["stats_end_date_block"]
        ["stats_end_date"]
        ["selected_date"]
    )

    view_type = (
        values["stats_view_block"]
        ["stats_view_select"]
        ["selected_option"]
        ["value"]
    )

    # =====================================================
    # 날짜 검증
    # =====================================================

    if start_date > end_date:

        ack(
            response_action="errors",
            errors={
                "stats_end_date_block": (
                    "종료일은 시작일보다 "
                    "빠를 수 없습니다."
                )
            },
        )

        return

    ack()

    # =====================================================
    # Slack 값 → DB 값
    # =====================================================

    db_region = (
        None
        if region == "all"
        else region
    )

    db_country = (
        None
        if country == "all"
        else country
    )

    # =====================================================
    # 표시용 조건
    # =====================================================

    region_label = {
        "all": "전체",
        "Asia": "아시아",
        "Europe": "유럽",
        "Africa": "아프리카",
        "Other": "기타",
    }.get(
        region,
        region,
    )

    country_label = (
        "전체 국가"
        if country == "all"
        else country
    )

    # =====================================================
    # 국가별 발생 기간(일)
    #
    # HPAI는 가금 / 가금 외를 각각 계산한다.
    # =====================================================

    if view_type == "duration":

        if disease == "HPAI":

            targets = [
                (
                    "HPAI - 가금 (Poultry)",
                    "HPAI",
                ),
                (
                    "HPAI - 가금 외 "
                    "(Non-poultry including wild birds)",
                    "HPAI_NON_POULTRY",
                ),
            ]

        else:

            targets = [
                (disease, disease)
            ]

        try:

            for label, code in targets:

                gap_days = get_gap_days(code)

                rows = get_outbreak_duration_stats(
                    disease_code=code,
                    start_date=start_date,
                    end_date=end_date,
                    region=db_region,
                    country=db_country,
                    gap_days=gap_days,
                )

                for message in build_duration_messages(
                    rows=rows,
                    disease=label,
                    region_label=region_label,
                    country_label=country_label,
                    start_date=start_date,
                    end_date=end_date,
                    gap_days=gap_days,
                ):

                    client.chat_postMessage(
                        channel=body["user"]["id"],
                        text=message,
                    )

                post_event_button(
                    client=client,
                    channel=body["user"]["id"],
                    code=code,
                    start_date=start_date,
                    end_date=end_date,
                    db_region=db_region,
                    db_country=db_country,
                )

        except Exception as e:

            print(
                "WAHIS 발생 기간 조회 오류: "
                f"{type(e).__name__}: {e}"
            )

            client.chat_postMessage(
                channel=body["user"]["id"],
                text=(
                    "❌ 발생 기간 조회 중 오류가 "
                    "발생했습니다.\n"
                    "터미널 로그를 확인해주세요."
                ),
            )

        return


    # =====================================================
    # HPAI
    #
    # HPAI는 WAHIS에서
    # 1. 가금 (Poultry)
    # 2. 가금 외 (Non-poultry including wild birds)
    #
    # 두 질병 코드로 관리되므로 각각 조회한다.
    # =====================================================

    if disease == "HPAI":

        try:
            hpai_rows = get_hpai_outbreak_stats(
                start_date=start_date,
                end_date=end_date,
                region=db_region,
                country=db_country,
            )

            # ---------------------------------------------
            # 가금
            # ---------------------------------------------

            poultry_result = build_matrix(
                hpai_rows["poultry"]
            )

            # ---------------------------------------------
            # 가금 외
            # ---------------------------------------------

            non_poultry_result = build_matrix(
                hpai_rows["non_poultry"]
            )

        except Exception as e:

            print(
                "WAHIS HPAI 통계 조회 오류: "
                f"{type(e).__name__}: {e}"
            )

            client.chat_postMessage(
                channel=body["user"]["id"],
                text=(
                    "❌ HPAI 발생 통계 조회 중 "
                    "오류가 발생했습니다.\n"
                    "터미널 로그를 확인해주세요."
                ),
            )

            return

        # =================================================
        # HPAI Matrix
        # =================================================

        if view_type == "matrix":

            # ---------------------------------------------
            # 가금 Matrix
            # ---------------------------------------------

            poultry_message = build_matrix_text(
                result=poultry_result,
                disease="HPAI - 가금 (Poultry)",
                region_label=region_label,
                country_label=country_label,
                start_date=start_date,
                end_date=end_date,
            )

            post_matrix_message(
                client=client,
                channel=body["user"]["id"],
                text=poultry_message,
            )

            # ---------------------------------------------
            # 가금 외 Matrix
            # ---------------------------------------------

            non_poultry_message = build_matrix_text(
                result=non_poultry_result,
                disease=(
                    "HPAI - 가금 외 "
                    "(Non-poultry including wild birds)"
                ),
                region_label=region_label,
                country_label=country_label,
                start_date=start_date,
                end_date=end_date,
            )

            post_matrix_message(
                client=client,
                channel=body["user"]["id"],
                text=non_poultry_message,
            )

        # =================================================
        # HPAI 국가별 총 발생건수
        # =================================================

        else:

            # ---------------------------------------------
            # 가금
            # ---------------------------------------------

            poultry_message = build_country_total_text(
                result=poultry_result,
                disease="HPAI - 가금 (Poultry)",
                region_label=region_label,
                country_label=country_label,
                start_date=start_date,
                end_date=end_date,
            )

            post_long_message(
                client=client,
                channel=body["user"]["id"],
                text=poultry_message,
            )

            post_event_button(
                client=client,
                channel=body["user"]["id"],
                code="HPAI",
                start_date=start_date,
                end_date=end_date,
                db_region=db_region,
                db_country=db_country,
            )

            # ---------------------------------------------
            # 가금 외
            # ---------------------------------------------

            non_poultry_message = build_country_total_text(
                result=non_poultry_result,
                disease=(
                    "HPAI - 가금 외 "
                    "(Non-poultry including wild birds)"
                ),
                region_label=region_label,
                country_label=country_label,
                start_date=start_date,
                end_date=end_date,
            )

            post_long_message(
                client=client,
                channel=body["user"]["id"],
                text=non_poultry_message,
            )

            post_event_button(
                client=client,
                channel=body["user"]["id"],
                code="HPAI_NON_POULTRY",
                start_date=start_date,
                end_date=end_date,
                db_region=db_region,
                db_country=db_country,
            )

        return

    # =====================================================
    # ASF / FMD / LSD
    #
    # 기존 방식 그대로 유지
    # =====================================================

    try:

        rows = get_outbreak_stats(
            disease_code=disease,
            start_date=start_date,
            end_date=end_date,
            region=db_region,
            country=db_country,
        )

        result = build_matrix(
            rows
        )

    except Exception as e:

        print(
            "WAHIS 통계 조회 오류: "
            f"{type(e).__name__}: {e}"
        )

        client.chat_postMessage(
            channel=body["user"]["id"],
            text=(
                "❌ WAHIS 발생 통계 조회 중 "
                "오류가 발생했습니다.\n"
                "터미널 로그를 확인해주세요."
            ),
        )

        return

    # =====================================================
    # Matrix
    # =====================================================

    if view_type == "matrix":

        message = build_matrix_text(
            result=result,
            disease=disease,
            region_label=region_label,
            country_label=country_label,
            start_date=start_date,
            end_date=end_date,
        )

        post_matrix_message(
            client=client,
            channel=body["user"]["id"],
            text=message,
        )

    # =====================================================
    # 국가별 총 발생건수
    # =====================================================

    else:

        message = build_country_total_text(
            result=result,
            disease=disease,
            region_label=region_label,
            country_label=country_label,
            start_date=start_date,
            end_date=end_date,
        )

        post_long_message(
            client=client,
            channel=body["user"]["id"],
            text=message,
        )

        post_event_button(
            client=client,
            channel=body["user"]["id"],
            code=disease,
            start_date=start_date,
            end_date=end_date,
            db_region=db_region,
            db_country=db_country,
        )

# =========================================================
# Socket Mode
# =========================================================
if __name__ == "__main__":

    print("=" * 60)
    print("WAHIS Slack Query App")
    print("=" * 60)
    print("Socket Mode 연결을 시작합니다.")
    print("종료하려면 Ctrl + C")
    print("=" * 60)

    handler = SocketModeHandler(
        app,
        SLACK_APP_TOKEN,
    )

    handler.start()