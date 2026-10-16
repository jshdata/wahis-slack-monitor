import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from apqa.quarantine_schedule import (PAIRS, completed_keys, eligible_through,
                                      pending_months, run_daily, validate_release)
from apqa.quarantine_statistics import SourceNotReady


def keys_through(end):
    from apqa.quarantine_statistics import months_between
    return {f"{m}:no{no}:type{t}" for m in months_between("2020-01", end) for no, t in PAIRS}


def release():
    return {"datasets": [{"source_no": no, "type_code": t,
                          "details": [{"case_count": 1}] if no == 2 else []}
                         for no, t in PAIRS]}


class ReleasePlanningTests(unittest.TestCase):
    def test_eleventh_and_year_boundary(self):
        self.assertEqual(eligible_through(date(2026, 11, 10)), "2026-09")
        self.assertEqual(eligible_through(date(2026, 11, 11)), "2026-10")
        self.assertEqual(eligible_through(date(2027, 1, 10)), "2026-11")
        self.assertEqual(eligible_through(date(2027, 1, 11)), "2026-12")

    def test_missing_old_month_survives_month_rollover_and_partial_completion(self):
        completed = keys_through("2026-09")
        completed.discard("2026-08:no4:type3")
        self.assertEqual(pending_months(date(2026, 11, 1), completed), ["2026-08"])
        self.assertEqual(pending_months(date(2026, 11, 11), completed), ["2026-08", "2026-10"])

    def test_zero_rejections_are_allowed_but_unconfirmed_trade_zeros_are_pending(self):
        data = release()
        validate_release(data)
        data["datasets"][0]["details"] = []
        with self.assertRaises(SourceNotReady):
            validate_release(data)
        data["datasets"].pop()
        with self.assertRaises(ValueError):
            validate_release(data)

    @patch("apqa.quarantine_schedule.get_connection")
    def test_failed_or_interrupted_readback_is_retried_even_if_data_was_committed(self, connect):
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [("2026-09:no2:type3",), ("2026-08:no2:type3",)],
            [(date(2026, 9, 1), "FAILED"), (date(2026, 8, 1), "COMPLETE")]]
        self.assertEqual(completed_keys(), {"2026-08:no2:type3"})


class DailyRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patches = {
            "ROOT": Path(self.temp.name), "completed_keys": keys_through("2026-09"),
            "ensure_attempt_schema": None, "claim_attempt": True, "finish_attempt": None,
            "collect": release(), "load_mysql": None,
            "verify_mysql": {"status": "VERIFIED"},
        }
        self.mocks = {}
        for name, value in patches.items():
            p = patch("apqa.quarantine_schedule." + name, value) if name == "ROOT" else patch(
                "apqa.quarantine_schedule." + name, return_value=value)
            self.mocks[name] = p.start()
            self.addCleanup(p.stop)
        self.mocks["collect"].side_effect = self.collect

    def collect(self, start, end, folder):
        folder.mkdir(parents=True, exist_ok=True)
        return release()

    def run_on(self, day, **kwargs):
        return run_daily(datetime(2026, 11, day, 1, 17, tzinfo=timezone.utc), **kwargs)

    def test_no_poll_before_eleventh_and_dry_run_never_claims_or_writes(self):
        self.assertEqual(self.run_on(10)["pending_months"], [])
        result = self.run_on(11, dry_run=True)
        self.assertEqual(result["pending_months"], ["2026-10"])
        self.mocks["collect"].assert_not_called()
        self.mocks["claim_attempt"].assert_not_called()

    def test_pending_retries_next_day_with_fresh_directory_then_stops_on_completion(self):
        self.mocks["collect"].side_effect = SourceNotReady("Not published")
        result = self.run_on(11)
        self.assertEqual(result["results"][0]["status"], "PENDING")
        self.assertEqual(result["results"][0]["next_retry_on"], "2026-11-12")
        self.mocks["load_mysql"].assert_not_called()
        first = self.mocks["collect"].call_args.args[2]
        self.mocks["collect"].side_effect = self.collect
        self.assertEqual(self.run_on(12)["results"][0]["status"], "COMPLETE")
        second = self.mocks["collect"].call_args.args[2]
        self.assertNotEqual(first, second)
        self.mocks["completed_keys"].return_value = keys_through("2026-10")
        self.assertEqual(self.run_on(13)["pending_months"], [])
        self.assertEqual(self.mocks["collect"].call_count, 2)

    def test_same_day_reentry_does_not_poll_again(self):
        self.mocks["claim_attempt"].return_value = False
        result = self.run_on(11)
        self.assertEqual(result["results"][0]["status"], "ALREADY_ATTEMPTED_TODAY")
        self.mocks["collect"].assert_not_called()

    def test_validation_failure_is_failed_and_not_loaded(self):
        self.mocks["collect"].side_effect = ValueError("Count mismatch")
        result = self.run_on(11)
        self.assertEqual(result["results"][0]["status"], "FAILED")
        self.mocks["load_mysql"].assert_not_called()
        self.assertEqual(self.mocks["finish_attempt"].call_args.args[2], "FAILED")

    def test_korean_calendar_is_used(self):
        # November 10 UTC is already November 11 in Korea.
        result = run_daily(datetime(2026, 11, 10, 16, 0, tzinfo=timezone.utc), dry_run=True)
        self.assertEqual(result["checked_on"], "2026-11-11")
        self.assertEqual(result["eligible_through"], "2026-10")


if __name__ == "__main__":
    unittest.main()
