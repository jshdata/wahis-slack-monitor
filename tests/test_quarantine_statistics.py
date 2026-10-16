import unittest
from unittest.mock import MagicMock, patch

from apqa.quarantine_statistics import _load_mysql_once, months_between, parse_excel


def document(body, totals, no=2):
    # Mirrors legacy Excel HTML: rowspan, colspan and an unclosed final tr.
    return ("<p>검사기간 : 202601 ~ 202601 통계분류 : 수입축산물</p>"
            "<table id=HeaderTable>" + body + "</table><table>" + totals + "</table>").encode("utf-8")


class QuarantineStatisticsTests(unittest.TestCase):
    def test_preserves_blank_labels_expands_spans_and_separates_units(self):
        raw = document(
            "<tr><th rowspan='3'></td><td rowspan='2'>난기타(ea)</td>"
            "<td>미국</td><td>1</td><td>10.0</td></tr>"
            "<tr><td>일본</td><td>2</td><td>20.0</td></tr>"
            "<tr><td></td><td>중국</td><td>1</td><td>0.1</td></tr>",
            "<tr><td colspan='3'>총 계 (kg)</td><td>1</td><td>0.1</td></tr>"
            "<tr><td colspan='3'>총 계 (ea)</td><td>3</td><td>30.0</td><tr>")
        rows, summaries, checks = parse_excel(raw, 2, 4, "2026-01")
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["product_category"] for r in rows], ["", "", ""])
        self.assertEqual(rows[1]["product_name"], "난기타(ea)")
        self.assertEqual(rows[2]["product_name"], "")
        self.assertEqual([r["unit"] for r in rows], ["ea", "ea", "kg"])
        self.assertEqual(len(summaries), 2)
        self.assertTrue(all(c["rounding_delta"] == "0.0" for c in checks))

    def test_rejection_reasons_remain_separate_and_subtotals_are_excluded(self):
        raw = document(
            "<tr><td rowspan='3'>육류</td><td rowspan='3'>쇠고기</td>"
            "<td rowspan='3'>미국</td><td>포장상태불량</td><td>1</td><td>0.1</td></tr>"
            "<tr><td>검역증미첨부</td><td>2</td><td>0.1</td></tr>"
            "<tr><td>국가계</td><td>3</td><td>0.3</td></tr>",
            "<tr><td colspan='4'>총 계 (kg)</td><td>3</td><td>0.3</td></tr>", no=4)
        rows, summaries, checks = parse_excel(raw, 4, 4, "2026-01")
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["rejection_reason"] for r in rows}, {"포장상태불량", "검역증미첨부"})
        self.assertEqual(len(summaries), 2)
        self.assertEqual(checks[0]["rounding_delta"], "-0.1")

    def test_rejects_missing_cases_wrong_month_and_large_quantity_mismatch(self):
        body = "<tr><td>육류</td><td>쇠고기</td><td>미국</td><td>1</td><td>1.0</td></tr>"
        for count, quantity in ((2, "1.0"), (1, "5.0")):
            raw = document(body, f"<tr><td>총 계 (kg)</td><td>{count}</td><td>{quantity}</td></tr>")
            with self.assertRaises(ValueError):
                parse_excel(raw, 2, 4, "2026-01")
        with self.assertRaises(ValueError):
            parse_excel(document(body, ""), 2, 4, "2026-02")
        self.assertEqual(list(months_between("2026-01", "2026-09")),
                         [f"2026-{month:02d}" for month in range(1, 10)])

    def test_identical_labels_in_unnamed_categories_preserve_both_source_rows(self):
        raw = document(
            "<tr><td></td><td>햄</td><td>스페인</td><td>1</td><td>0.2</td></tr>"
            "<tr><td></td><td>햄</td><td>스페인</td><td>27</td><td>15,424.5</td></tr>",
            "<tr><td>총 계 (kg)</td><td>28</td><td>15,424.7</td></tr>")
        rows, _, checks = parse_excel(raw, 2, 4, "2026-01")
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["source_row"], rows[1]["source_row"])
        self.assertEqual([r["case_count"] for r in rows], [1, 27])
        self.assertEqual(checks[0]["case_count"], 28)


class QuarantineBatchStorageTests(unittest.TestCase):
    def dataset(self, no):
        return {
            "collection_key": f"2020-01:no{no}:type3", "month": "2020-01",
            "source_no": no, "type_code": 3, "type_name": "수입동물",
            "fetched_at": "2026-10-16T00:00:00+00:00",
            "source_url": "https://eminwon.qia.go.kr/statistics/",
            "source_file": "fixture.xls", "source_sha256": "a" * 64,
            "detail_count": 1, "summary_count": 1, "blank_category_count": 0,
            "validation": [], "request": {},
            "details": [{"product_category": "포유류", "product_name": "개",
                         "country_name": "미국", "rejection_reason": "검역증미첨부" if no == 4 else "",
                         "case_count": 2, "quantity": "3", "unit": "마리", "source_row": 1}],
            "summaries": [{"row_index": 0, "level": "총계", "unit": "마리",
                           "labels": ["총 계 (마리)"], "case_count": 2, "quantity": "3"}],
        }

    @patch("database.db.get_connection")
    def test_replay_uses_stable_keys_and_deletes_only_requested_snapshots(self, connect):
        connection = MagicMock()
        connect.return_value = connection
        cur = connection.cursor.return_value.__enter__.return_value
        datasets = [self.dataset(2), self.dataset(4)]
        counts = [[(d["collection_key"], 1, 2)] for d in datasets]
        cur.fetchall.side_effect = counts + counts
        for _ in range(2):
            _load_mysql_once({"datasets": datasets})
        deletes = [c for c in cur.execute.call_args_list if c.args[0].startswith("DELETE")]
        self.assertEqual(len(deletes), 6)
        for call in deletes:
            self.assertEqual(call.args[1], [d["collection_key"] for d in datasets])
            self.assertIn("WHERE collection_key IN", call.args[0])
        inserts = [c.args[1] for c in cur.executemany.call_args_list
                   if "INSERT INTO qia_trade_statistics" in c.args[0]]
        self.assertEqual(inserts[0], inserts[1])
        self.assertEqual(connection.commit.call_count, 4)
        connection.rollback.assert_not_called()

    @patch("database.db.get_connection")
    def test_failed_readback_rolls_back_batch(self, connect):
        connection = connect.return_value
        cur = connection.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = []
        with self.assertRaisesRegex(ValueError, "readback mismatch"):
            _load_mysql_once({"datasets": [self.dataset(2)]})
        connection.rollback.assert_called_once()
        # Only schema setup committed; the failed data batch did not.
        connection.commit.assert_called_once()

    @patch("database.db.get_connection")
    def test_same_display_labels_have_distinct_database_keys(self, connect):
        ds = self.dataset(2)
        ds["details"].append(dict(ds["details"][0], source_row=2, case_count=27))
        ds["detail_count"] = 2
        cur = connect.return_value.cursor.return_value.__enter__.return_value
        cur.fetchall.side_effect = [[(ds["collection_key"], 2, 29)], []]
        _load_mysql_once({"datasets": [ds]})
        inserts = [c.args[1] for c in cur.executemany.call_args_list
                   if "INSERT INTO qia_trade_statistics" in c.args[0]]
        self.assertNotEqual(inserts[0][0][0], inserts[0][1][0])


if __name__ == "__main__":
    unittest.main()
