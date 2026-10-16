"""Slack filters and HTML links for WAHIS animal populations."""
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import BoundedSemaphore, Lock
from uuid import uuid4
from zoneinfo import ZoneInfo

from database.population_db import load_population, load_population_options
from slack.population_report import build_population_report, display_label
from slack.stats_report_server import REPORT_TTL_SECONDS, report_url

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="animal-population")
SLOTS = BoundedSemaphore(4)
logger = logging.getLogger(__name__)
FIELDS = {"region": "권역", "country": "국가", "animal_type": "동물 타입", "animal_category": "동물 카테고리"}
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
            _OPTIONS = load_population_options()
            _OPTIONS_AT = time.monotonic()
    return _OPTIONS


def field_choices(options, field):
    return options[field]


def read_filters(values, options):
    result = {}
    for field in FIELDS:
        state = values.get(f"population_{field}", {}).get("select", {})
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
            "action_id": "population_link", "text": {"type": "plain_text", "text": "동물 개체수 HTML 열기"},
            "url": url}]})
    return {"type": "modal", "title": {"type": "plain_text", "text": "동물 개체수 조회"},
            "close": {"type": "plain_text", "text": "닫기"}, "blocks": blocks}


def settings_view():
    view = message_view("저장된 전체 연도의 동물 수·사육시설 수·도축 고기 중량을 조회합니다.\n"
                        "권역·국가·동물 타입·카테고리는 선택하지 않으면 전체입니다.\n"
                        "동물 타입은 육상동물 / 수생동물입니다. 연도는 표의 가로 열로 표시됩니다.")
    view.update(callback_id="population_settings", submit={"type": "plain_text", "text": "표 만들기"})
    for field, title in FIELDS.items():
        view["blocks"].append({"type": "input", "block_id": f"population_{field}",
            "optional": True, "label": {"type": "plain_text", "text": title},
            "element": {"type": "multi_external_select", "action_id": "select",
                        "placeholder": {"type": "plain_text", "text": "전체 · 검색하여 여러 항목 선택"},
                        "min_query_length": 0}})
    # Each external select needs a distinct options action, while the state key
    # is shared with the corresponding input block's field name.
    for block in view["blocks"][1:]:
        block["element"]["action_id"] = block["block_id"] + "_select"
    return view


def normalize_values(values):
    # External action IDs are distinct; read_filters uses a common state shape.
    return {key: {"select": value.get(key + "_select", value.get("select", {}))}
            for key, value in values.items()}


def register_population_handlers(app, reports):
    @app.action("population_open")
    def open_settings(ack, body, client):
        ack()
        if not SLOTS.acquire(blocking=False):
            client.views_push(trigger_id=body["trigger_id"], view=message_view("다른 표를 처리 중입니다. 잠시 후 다시 시도해주세요."))
            return
        try:
            response = client.views_push(trigger_id=body["trigger_id"], view=message_view("동물 개체수 조회의 권역·국가·동물 분류를 준비하고 있습니다."))
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
                logger.warning("Population options failed: %s", type(error).__name__)
                result = message_view("선택 항목을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
            finally:
                SLOTS.release()
            try:
                client.views_update(view_id=view_id, view=result)
            except Exception as error:
                logger.warning("Population options modal update failed: %s", type(error).__name__)
        try:
            POOL.submit(prepare)
        except Exception:
            SLOTS.release()
            raise

    @app.action("population_link")
    def acknowledge_link(ack):
        ack()

    @app.options("population_region_select")
    @app.options("population_animal_type_select")
    @app.options("population_animal_category_select")
    @app.options("population_country_select")
    def suggest(ack, body):
        try:
            options = current_options()
            field = body["action_id"].removeprefix("population_").removesuffix("_select")
            choices = field_choices(options, field)
            query = (body.get("value") or "").casefold()
            ack(options=[{"text": {"type": "plain_text", "text": display_label(field, name)[:75]},
                          "value": option_token(name)}
                         for name in choices if query in name.casefold() or query in display_label(field, name).casefold()][:100])
        except Exception as error:
            logger.warning("Population suggestions failed: %s", type(error).__name__)
            ack(options=[])

    @app.view("population_settings")
    def generate(ack, body, view, client):
        values = view.get("state", {}).get("values", {})
        if not SLOTS.acquire(blocking=False):
            ack(response_action="errors", errors={"population_region": "다른 표를 처리 중입니다. 잠시 후 다시 시도해주세요."})
            return
        try:
            ack(response_action="update", view=message_view("동물 개체수 표를 만들고 있습니다."))
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
                data = load_population(filters["region"], filters["country"], filters["animal_type"], filters["animal_category"])
                today = datetime.now(ZoneInfo("Asia/Seoul")).date()
                reports[key] = {"html": build_population_report(data, today, filters),
                                "expires_at": time.time() + REPORT_TTL_SECONDS}
                while len(reports) > 30:
                    reports.pop(next(iter(reports)), None)
                result = message_view("동물 개체수 표가 준비됐습니다. 아래 버튼으로 브라우저에서 열어보세요.\n"
                                      "미보고 값은 —로 표시합니다. 링크는 1시간 동안 유효합니다.", url)
            except Exception as error:
                logger.warning("Population report failed: %s", type(error).__name__)
                result = message_view(str(error) if isinstance(error, ValueError) else
                                      "동물 개체수 표를 만들지 못했습니다. DB 연결과 서버 로그를 확인해주세요.")
            finally:
                SLOTS.release()
            try:
                client.views_update(view_id=view_id, view=result)
            except Exception as error:
                logger.warning("Population modal update failed: %s", type(error).__name__)
        try:
            POOL.submit(work)
        except Exception:
            SLOTS.release()
            raise
