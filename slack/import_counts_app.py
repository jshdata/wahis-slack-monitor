"""Slack tag filters and HTML links for QIA import case counts."""
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import BoundedSemaphore, Lock
from uuid import uuid4
from zoneinfo import ZoneInfo

from database.import_counts_db import load_import_counts, load_import_options
from slack.import_counts_report import build_import_counts_report
from slack.stats_report_server import REPORT_TTL_SECONDS, report_url

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="import-counts")
SLOTS = BoundedSemaphore(4)
logger = logging.getLogger(__name__)
FIELDS = {"category": "품목", "product": "품명", "country": "국가"}
_OPTIONS = None
_OPTIONS_AT = 0
_OPTIONS_LOCK = Lock()


def option_token(value):
    # Slack values have a length limit; hashes also distinguish a blank label
    # from no selection (which means all).
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def current_options(refresh=False):
    global _OPTIONS, _OPTIONS_AT
    if _OPTIONS is not None and (not refresh or time.monotonic() - _OPTIONS_AT < 300):
        return _OPTIONS
    with _OPTIONS_LOCK:
        if _OPTIONS is None or (refresh and time.monotonic() - _OPTIONS_AT >= 300):
            _OPTIONS = load_import_options()
            _OPTIONS_AT = time.monotonic()
    return _OPTIONS


def field_choices(options, field):
    return sorted({product for _, product in options["product"]}) if field == "product" else options[field]


def read_filters(values, options):
    result = {}
    for field in FIELDS:
        state = values.get(f"qia_import_{field}", {}).get("select", {})
        mapping = {option_token(v): v for v in field_choices(options, field)}
        selected = state.get("selected_options") or []
        if any(o["value"] not in mapping for o in selected):
            raise ValueError("선택 항목이 변경됐습니다. 필터를 다시 선택해주세요.")
        result[field] = [mapping[o["value"]] for o in selected]
    return result


def message_view(text, url=None):
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if url:
        blocks.append({"type": "actions", "elements": [{"type": "button",
            "action_id": "qia_import_link", "text": {"type": "plain_text", "text": "수입건수 HTML 열기"},
            "url": url}]})
    return {"type": "modal", "title": {"type": "plain_text", "text": "수입건수"},
            "close": {"type": "plain_text", "text": "닫기"}, "blocks": blocks}


def settings_view():
    view = message_view("2020년 1월부터 저장된 최신 월까지의 수입건수를 조회합니다.\n"
                        "품목·품명·국가는 선택하지 않으면 전체입니다.")
    view.update(callback_id="qia_import_settings", submit={"type": "plain_text", "text": "표 만들기"})
    for field, title in FIELDS.items():
        view["blocks"].append({"type": "input", "block_id": f"qia_import_{field}",
            "optional": True, "label": {"type": "plain_text", "text": title},
            "element": {"type": "multi_external_select", "action_id": "select",
                        "placeholder": {"type": "plain_text", "text": "전체 · 검색하여 여러 항목 선택"},
                        "min_query_length": 0}})
    # Each external select needs a distinct options action, while the state key
    # is shared with the corresponding input block's field name.
    for block in view["blocks"][1:]:
        block["element"]["action_id"] = block["block_id"] + "_select"
    modes = [{"text": {"type": "plain_text", "text": label}, "value": value}
             for value, label in (("year", "연도별"), ("month", "월별"))]
    view["blocks"].append({"type": "input", "block_id": "qia_import_mode",
        "label": {"type": "plain_text", "text": "표시 단위"},
        "element": {"type": "static_select", "action_id": "select", "options": modes,
                    "initial_option": modes[0]}})
    return view


def normalize_values(values):
    # External action IDs are distinct; read_filters uses a common state shape.
    return {key: {"select": value.get(key + "_select", value.get("select", {}))}
            for key, value in values.items()}


def register_import_counts_handlers(app, reports):
    @app.action("qia_import_open")
    def open_settings(ack, body, client):
        ack()
        if not SLOTS.acquire(blocking=False):
            client.views_push(trigger_id=body["trigger_id"], view=message_view("다른 표를 처리 중입니다. 잠시 후 다시 시도해주세요."))
            return
        try:
            response = client.views_push(trigger_id=body["trigger_id"], view=message_view("수입 통계의 품목·품명·국가를 준비하고 있습니다."))
        except Exception:
            SLOTS.release()
            raise
        view_id = response["view"]["id"]

        def prepare():
            try:
                # Load before presenting the selects so options acknowledgments
                # never wait for the first database scan or a TTL rollover.
                current_options(refresh=True)
                result = settings_view()
            except Exception as error:
                logger.warning("Import options failed: %s", type(error).__name__)
                result = message_view("선택 항목을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
            finally:
                SLOTS.release()
            try:
                client.views_update(view_id=view_id, view=result)
            except Exception as error:
                logger.warning("Import options modal update failed: %s", type(error).__name__)
        try:
            POOL.submit(prepare)
        except Exception:
            SLOTS.release()
            raise

    @app.action("qia_import_link")
    def acknowledge_link(ack):
        ack()

    @app.options("qia_import_category_select")
    @app.options("qia_import_product_select")
    @app.options("qia_import_country_select")
    def suggest(ack, body):
        try:
            options = current_options()
            field = body["action_id"].removeprefix("qia_import_").removesuffix("_select")
            choices = field_choices(options, field)
            if field == "product":
                values = normalize_values(body.get("view", {}).get("state", {}).get("values", {}))
                categories = read_filters(values, options)["category"]
                if categories:
                    choices = sorted({product for category, product in options["product"] if category in categories})
            query = (body.get("value") or "").casefold()
            ack(options=[{"text": {"type": "plain_text", "text": (name or "(공백)")[:75]},
                          "value": option_token(name)}
                         for name in choices if query in (name or "(공백)").casefold()][:100])
        except Exception as error:
            logger.warning("Import suggestions failed: %s", type(error).__name__)
            ack(options=[])

    @app.view("qia_import_settings")
    def generate(ack, body, view, client):
        values = view.get("state", {}).get("values", {})
        mode = (values.get("qia_import_mode", {}).get("select", {}).get("selected_option") or {}).get("value", "year")
        if mode not in ("year", "month"):
            ack(response_action="errors", errors={"qia_import_mode": "연도별 또는 월별을 선택해주세요."})
            return
        if not SLOTS.acquire(blocking=False):
            ack(response_action="errors", errors={"qia_import_mode": "다른 표를 처리 중입니다. 잠시 후 다시 시도해주세요."})
            return
        try:
            ack(response_action="update", view=message_view("수입건수 표를 만들고 있습니다."))
        except Exception:
            SLOTS.release()
            raise
        view_id = view["id"]

        def work():
            try:
                filters = read_filters(normalize_values(values), current_options())
                key = uuid4().hex
                url = report_url(key)
                if not url:
                    raise ValueError("Railway 공개 도메인 또는 STATS_REPORT_BASE_URL을 설정해주세요.")
                data = load_import_counts(filters["category"], filters["product"], filters["country"])
                today = datetime.now(ZoneInfo("Asia/Seoul")).date()
                reports[key] = {"html": build_import_counts_report(data, mode, today, filters),
                                "expires_at": time.time() + REPORT_TTL_SECONDS}
                while len(reports) > 30:
                    reports.pop(next(iter(reports)), None)
                result = message_view("수입건수 표가 준비됐습니다. 아래 버튼으로 브라우저에서 열어보세요.\n"
                                      "전체 기간의 건수가 모두 0인 행은 제외합니다. 링크는 1시간 동안 유효합니다.", url)
            except Exception as error:
                logger.warning("Import count report failed: %s", type(error).__name__)
                result = message_view(str(error) if isinstance(error, ValueError) else
                                      "수입건수 표를 만들지 못했습니다. DB 연결과 서버 로그를 확인해주세요.")
            finally:
                SLOTS.release()
            try:
                client.views_update(view_id=view_id, view=result)
            except Exception as error:
                logger.warning("Import count modal update failed: %s", type(error).__name__)
        try:
            POOL.submit(work)
        except Exception:
            SLOTS.release()
            raise
