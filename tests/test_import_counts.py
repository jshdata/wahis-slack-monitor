import unittest
from datetime import date
from unittest.mock import MagicMock, Mock, patch

from database.import_counts_db import load_import_counts, month_range
from slack.import_counts_app import (normalize_values, option_token, read_filters,
                                     register_import_counts_handlers, settings_view)
from slack.import_counts_report import build_import_counts_report, import_count_matrix


class ImportCountReportTests(unittest.TestCase):
    def data(self):
        return {"latest_month": date(2026, 9, 1), "rows": [
            ("육류", "쇠고기", "미국", date(2020, 1, 1), 2),
            ("육류", "쇠고기", "미국", date(2020, 2, 1), 3),
            ("육류", "쇠고기", "미국", date(2026, 9, 1), 4),
            ("", "햄", "스페인", date(2024, 1, 1), 1),
            ("", "햄", "스페인", date(2024, 1, 1), 27),
            ("육류", "쇠고기", "일본", date(2021, 1, 1), 0),
        ]}

    def test_years_sum_months_and_separate_source_rows_and_omit_all_zero(self):
        periods, rows, totals = import_count_matrix(self.data(), "year")
        self.assertEqual(periods, list(range(2020, 2027)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(dict(rows)[("육류", "쇠고기", "미국")], [5, 0, 0, 0, 0, 0, 4])
        self.assertEqual(totals, [5, 0, 0, 0, 28, 0, 4])

    def test_months_keep_all_81_columns_even_for_a_single_recent_hit(self):
        data = {"latest_month": date(2026, 9, 1), "rows": self.data()["rows"][2:3]}
        periods, rows, totals = import_count_matrix(data, "month")
        self.assertEqual(len(periods), 81)
        self.assertEqual((periods[0], periods[-1]), ("2020-01", "2026-09"))
        self.assertEqual(rows[0][1], [0] * 80 + [4])
        self.assertEqual(sum(totals), 4)
        self.assertEqual(len(import_count_matrix(dict(data, rows=[]), "month")[0]), 81)

    def test_html_escapes_names_and_uses_fixed_keys_and_partial_year_note(self):
        data = {"latest_month": date(2026, 9, 1), "rows": [
            ("", "</td><script>alert(1)</script>", "미국", date(2026, 9, 1), 1)]}
        result = build_import_counts_report(data, "month", date(2026, 10, 16))
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)
        self.assertIn('colspan="9"', result)
        self.assertIn("2026년은 1~9월 자료", result)
        self.assertNotIn("2026-10", result.split("조회 기준:")[0])
        self.assertIn('class="key k2"', result)


class ImportCountDatabaseTests(unittest.TestCase):
    @patch("database.import_counts_db.get_connection")
    def test_import_only_query_with_parameterized_blank_and_country_filters(self, connect):
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        coverage = [(m, t) for m in month_range(date(2020, 2, 1)) for t in (3, 4)]
        cursor.fetchall.side_effect = [coverage, [("", "햄", "미국", date(2020, 1, 1), 28)]]
        result = load_import_counts([""], ["햄"], ["미국", "' OR 1=1 --"])
        sql, params = cursor.execute.call_args.args
        self.assertIn("FROM qia_trade_statistics", sql)
        self.assertIn("statistics_type IN (3,4)", sql)
        self.assertNotIn("qia_rejection_statistics", sql)
        self.assertNotIn("' OR 1=1 --", sql)
        self.assertEqual(params[-4:], ["", "햄", "미국", "' OR 1=1 --"])
        self.assertEqual(result["latest_month"], date(2020, 2, 1))
        self.assertEqual(result["rows"][0][-1], 28)
        connect.return_value.close.assert_called_once()

    @patch("database.import_counts_db.get_connection")
    def test_missing_collection_is_not_silently_reported_as_zero(self, connect):
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(date(2020, 1, 1), 3)]
        with self.assertRaisesRegex(ValueError, "미수집"):
            load_import_counts()
        self.assertEqual(cursor.execute.call_count, 1)


class ImportCountSlackTests(unittest.TestCase):
    def test_default_all_filters_are_searchable_tags_and_no_date_range(self):
        view = settings_view()
        blocks = {b.get("block_id"): b for b in view["blocks"]}
        for field in ("category", "product", "country"):
            block = blocks[f"qia_import_{field}"]
            self.assertTrue(block["optional"])
            self.assertEqual(block["element"]["type"], "multi_external_select")
            self.assertNotIn("initial_options", block["element"])
        self.assertEqual(blocks["qia_import_mode"]["element"]["initial_option"]["value"], "year")
        self.assertNotIn("datepicker", str(view))
        self.assertEqual(read_filters({}, {"category": [], "product": [], "country": []}),
                         {"category": [], "product": [], "country": []})

    def test_blank_selection_is_distinct_from_all(self):
        raw = {"qia_import_category": {"qia_import_category_select": {
            "selected_options": [{"value": option_token("")}]}}}
        options = {"category": ["", "육류"], "product": [], "country": []}
        self.assertEqual(read_filters(normalize_values(raw), options)["category"], [""])

    @patch("slack.import_counts_app.POOL")
    @patch("slack.import_counts_app.current_options", return_value={"category": [], "product": [], "country": []})
    @patch("slack.import_counts_app.load_import_counts", return_value={"latest_month": date(2026, 9, 1), "rows": []})
    @patch("slack.import_counts_app.report_url", return_value="https://example.test/reports/token")
    def test_modal_creates_private_html_link(self, url, load, options, pool):
        handlers = {}
        class App:
            def action(self, name):
                return self.register(name)
            def options(self, name):
                return self.register(name)
            def view(self, name):
                return self.register(name)
            def register(self, name):
                def decorator(function):
                    handlers[name] = function
                    return function
                return decorator
        reports = {}
        pool.submit.side_effect = lambda work: work()
        register_import_counts_handlers(App(), reports)
        client = MagicMock()
        ack = Mock()
        view = {"id": "V1", "state": {"values": {"qia_import_mode": {"select": {
            "selected_option": {"value": "month"}}}}}}
        handlers["qia_import_settings"](ack, {"view": view}, view, client)
        ack.assert_called_once()
        load.assert_called_once_with([], [], [])
        html = next(iter(reports.values()))["html"]
        self.assertIn("81</strong>", html)
        client.views_update.assert_called_once()
        client.chat_postMessage.assert_not_called()

    @patch("slack.import_counts_app.POOL")
    @patch("slack.import_counts_app.current_options")
    def test_filter_choices_are_prepared_before_selects_are_shown(self, options, pool):
        handlers = {}
        class App:
            def action(self, name):
                return self.register(name)
            def options(self, name):
                return self.register(name)
            def view(self, name):
                return self.register(name)
            def register(self, name):
                def decorator(function):
                    handlers[name] = function
                    return function
                return decorator
        events = []
        options.side_effect = lambda **kwargs: events.append("loaded")
        pool.submit.side_effect = lambda work: work()
        register_import_counts_handlers(App(), {})
        client = MagicMock()
        client.views_push.return_value = {"view": {"id": "V1"}}
        client.views_update.side_effect = lambda **kwargs: events.append("shown")
        ack = Mock(side_effect=lambda: events.append("ack"))
        handlers["qia_import_open"](ack, {"trigger_id": "T1"}, client)
        self.assertEqual(events, ["ack", "loaded", "shown"])
        options.assert_called_once_with(refresh=True)
        self.assertEqual(client.views_update.call_args.kwargs["view"]["callback_id"], "qia_import_settings")


if __name__ == "__main__":
    unittest.main()
