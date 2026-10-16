"""Monthly QIA No2/No4 Excel collection, validation, and MySQL loading.

The .xls downloads contain HTML, not binary Excel. Original bytes and source
summaries are retained; blank category labels are intentionally preserved.
"""
import argparse
import hashlib
import html as html_module
import json
import re
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://eminwon.qia.go.kr/statistics/"
TYPES = {1: "수출동물", 2: "수출축산물", 3: "수입동물", 4: "수입축산물"}
TABLES = {2: "qia_trade_statistics", 4: "qia_rejection_statistics"}
ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)(?:</tr>|(?=<tr\b)|(?=</table>))", re.I | re.S)
CELL_RE = re.compile(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", re.I | re.S)
NUMBER_RE = re.compile(r"^\d[\d,]*(?:\.\d+)?$")


class SourceNotReady(ValueError):
    """The source identifies the requested dataset but supplies no usable table."""


def clean(value):
    return " ".join(html_module.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


def expand_rows(table):
    """Expand both spans; tolerate legacy HTML whose th closes with /td."""
    spans = {}
    for row_index, match in enumerate(ROW_RE.finditer(table)):
        grid = {col: value for col, (end, value) in spans.items() if end >= row_index}
        spans = {col: span for col, span in spans.items() if span[0] >= row_index}
        col = 0
        for cell in CELL_RE.finditer(match[1]):
            while col in grid:
                col += 1
            attrs, value = cell[1], clean(cell[2])
            rs = re.search(r"rowspan=['\"]?(\d+)", attrs, re.I)
            cs = re.search(r"colspan=['\"]?(\d+)", attrs, re.I)
            row_span, col_span = int(rs[1]) if rs else 1, int(cs[1]) if cs else 1
            for offset in range(col_span):
                grid[col + offset] = value
                if row_span > 1:
                    spans[col + offset] = (row_index + row_span - 1, value)
            col += col_span
        if grid:
            yield [grid.get(i, "") for i in range(max(grid) + 1)]


def parse_excel(raw, no, type_code, month):
    try:
        document = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        document = raw.decode("cp949")
    text = clean(document)
    period = month.replace("-", "")
    if not re.search(rf"검사기간\s*:\s*{period}\s*~\s*{period}", text):
        raise ValueError(f"Wrong/missing period for {month} No{no}")
    if not re.search(rf"통계분류\s*:\s*{TYPES[type_code]}", text):
        raise ValueError("Wrong/missing statistics type")
    start = re.search(r"<table\b[^>]*\bid=['\"]?HeaderTable\b[^>]*>", document, re.I)
    if not start:
        start = re.search(r"<table\b[^>]*bgcolor=['\"]#B3D6D2['\"][^>]*>", document, re.I)
    if not start:
        raise SourceNotReady("Missing data table; empty results need explicit verification")
    data_end = document.find("</table>", start.end())
    if data_end < 0:
        raise ValueError("Unterminated data table")
    tables = [document[start.start():data_end + len("</table>")]]
    tables += re.findall(r"<table\b[^>]*>.*?</table>", document[data_end + 8:], re.I | re.S)
    width = 5 if no == 2 else 6
    details, summaries = [], []
    for table_index, table in enumerate(tables):
        for row_number, cells in enumerate(expand_rows(table)):
            if len(cells) < 3 or not all(NUMBER_RE.fullmatch(x) for x in cells[-2:]):
                continue
            count = Decimal(cells[-2].replace(",", ""))
            quantity = Decimal(cells[-1].replace(",", ""))
            if count != count.to_integral_value():
                raise ValueError("Fractional case count")
            labels = cells[:-2]
            summary_label = next((v for v in labels if re.match(r"^(품명계|품목계|국가계|총\s*계)", v)), None)
            if summary_label is not None:
                unit_match = re.search(r"\((kg|ea|마리|군)\)", summary_label)
                level = re.sub(r"\s", "", summary_label.split("(")[0])
                summaries.append({"row_index": len(summaries), "level": level,
                                  "unit": unit_match[1] if unit_match else "",
                                  "labels": labels, "case_count": int(count),
                                  "quantity": str(quantity)})
                continue
            if table_index != 0 or len(cells) != width:
                raise ValueError(f"Unexpected numeric row at {row_number}: {cells}")
            category, product, country = cells[:3]
            if type_code in (1, 3):
                unit = "군" if "(군)" in product or "꿀벌" in product else "마리"
            else:
                unit = "ea" if re.search(r"\(ea\)", product, re.I) else "kg"
            reason = cells[3] if no == 4 else ""
            if no == 4 and not reason:
                raise ValueError("Missing rejection reason")
            details.append({"source_row": row_number, "product_category": category,
                            "product_name": product, "country_name": country,
                            "rejection_reason": reason, "unit": unit,
                            "case_count": int(count), "quantity": str(quantity)})
    totals = {r["unit"]: r for r in summaries if r["level"] == "총계"}
    if not totals:
        raise SourceNotReady("No source grand totals")
    if len(totals) != len([r for r in summaries if r["level"] == "총계"]):
        raise ValueError("Repeated source grand totals")
    validations = []
    for unit in sorted(set(totals) | {r["unit"] for r in details}):
        if unit not in totals:
            raise ValueError(f"No total for detail unit {unit}")
        rows = [r for r in details if r["unit"] == unit]
        actual_count = sum(r["case_count"] for r in rows)
        actual_quantity = sum((Decimal(r["quantity"]) for r in rows), Decimal(0))
        expected = totals[unit]
        if actual_count != expected["case_count"]:
            raise ValueError(f"Count mismatch {month} No{no} type={type_code} {unit}: "
                             f"{actual_count} != {expected['case_count']}")
        delta = actual_quantity - Decimal(expected["quantity"])
        # The site displays kg/ea to one decimal, independently of aggregates.
        tolerance = Decimal("0.05") * (len(rows) + 1) if unit in ("kg", "ea") else Decimal(0)
        if abs(delta) > tolerance:
            raise ValueError(f"Quantity mismatch beyond display rounding: {delta} {unit}")
        validations.append({"unit": unit, "case_count": actual_count,
                            "source_quantity": expected["quantity"],
                            "detail_quantity": str(actual_quantity),
                            "rounding_delta": str(delta), "rounding_tolerance": str(tolerance)})
    # Two unnamed categories may contain the same display product/country.
    # Keep every source row; unit totals validate that none were lost or merged.
    return details, summaries, validations


def months_between(start, end):
    current, last = date.fromisoformat(start + "-01"), date.fromisoformat(end + "-01")
    if current > last:
        raise ValueError("Start exceeds end")
    while current <= last:
        yield current.strftime("%Y-%m")
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)


def collect(start, end, output, delay=0.6):
    output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=Retry(
        total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"))))
    datasets = []
    for month in months_between(start, end):
        for no, type_codes in ((2, (1, 2, 3, 4)), (4, (3, 4))):
            for type_code in type_codes:
                filename = f"{month}_no{no}_type{type_code}.xls"
                path = output / filename
                payload = {"s_Type_Statistics": str(type_code),
                           "s_Dte1_Statistics": month.replace("-", ""),
                           "s_Dte2_Statistics": month.replace("-", ""),
                           "s_Nat_Statistics": "total", "s_Prod_Statistics": "total",
                           "s_ProdDetail_Statistics": "total", "toYearParam_Statistics": month[:4]}
                url = f"{BASE_URL}statistics_No{no}_Excel.do"
                if path.exists():
                    raw = path.read_bytes()
                    fetched_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
                else:
                    response = session.post(url, data=payload, timeout=(15, 90))
                    response.raise_for_status()
                    raw = response.content
                    path.write_bytes(raw)
                    fetched_at = datetime.now(timezone.utc).isoformat()
                    time.sleep(delay)
                details, summaries, checks = parse_excel(raw, no, type_code, month)
                dataset = {"collection_key": f"{month}:no{no}:type{type_code}",
                           "month": month, "source_no": no, "type_code": type_code,
                           "type_name": TYPES[type_code], "source_url": url,
                           "source_file": str(path.relative_to(ROOT)),
                           "source_sha256": hashlib.sha256(raw).hexdigest(),
                           "fetched_at": fetched_at, "request": payload,
                           "detail_count": len(details), "summary_count": len(summaries),
                           "blank_category_count": sum(not r["product_category"] for r in details),
                           "blank_product_count": sum(not r["product_name"] for r in details),
                           "blank_country_count": sum(not r["country_name"] for r in details),
                           "validation": checks, "details": details, "summaries": summaries}
                datasets.append(dataset)
                print(f"VALIDATED {dataset['collection_key']} rows={len(details)} "
                      f"blank_categories={dataset['blank_category_count']}", flush=True)
    manifest = {"start": start, "end": end, "dataset_count": len(datasets), "datasets": datasets}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _load_mysql_once(manifest):
    from database.db import get_connection
    connection = get_connection()
    try:
        with connection.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS qia_statistics_collections (
                collection_key VARCHAR(40) PRIMARY KEY, reference_month DATE NOT NULL,
                source_no INT NOT NULL, statistics_type INT NOT NULL,
                statistics_type_name VARCHAR(30) NOT NULL, fetched_at DATETIME NOT NULL,
                source_url TEXT NOT NULL, source_file TEXT NOT NULL,
                source_sha256 CHAR(64) NOT NULL, detail_count INT NOT NULL,
                summary_count INT NOT NULL, blank_category_count INT NOT NULL,
                validation_json JSON NOT NULL, request_json JSON NOT NULL,
                status VARCHAR(20) NOT NULL,
                INDEX idx_qia_month (reference_month, source_no, statistics_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            for table in TABLES.values():
                cur.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
                    record_key CHAR(64) PRIMARY KEY, collection_key VARCHAR(40) NOT NULL,
                    reference_month DATE NOT NULL, statistics_type INT NOT NULL,
                    statistics_type_name VARCHAR(30) NOT NULL,
                    product_category VARCHAR(200) NOT NULL DEFAULT '',
                    product_name VARCHAR(200) NOT NULL, country_name VARCHAR(150) NOT NULL,
                    rejection_reason VARCHAR(250) NOT NULL DEFAULT '',
                    case_count BIGINT NOT NULL, quantity DECIMAL(24,6) NOT NULL,
                    unit VARCHAR(10) NOT NULL, source_row INT NOT NULL,
                    collected_at DATETIME NOT NULL,
                    INDEX idx_qia_detail_collection (collection_key),
                    INDEX idx_qia_detail_analysis (reference_month, statistics_type, country_name)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            cur.execute("""CREATE TABLE IF NOT EXISTS qia_statistics_summaries (
                collection_key VARCHAR(40) NOT NULL, row_index INT NOT NULL,
                summary_level VARCHAR(30) NOT NULL, unit VARCHAR(10) NOT NULL,
                labels_json JSON NOT NULL, case_count BIGINT NOT NULL,
                quantity DECIMAL(24,6) NOT NULL,
                PRIMARY KEY (collection_key, row_index)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        connection.commit()
        datasets = manifest["datasets"]
        keys = [d["collection_key"] for d in datasets]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate collection keys")
        # Up to twelve months per transaction; bulk statements avoid thousands
        # of network round trips when backfilling several years.
        for offset in range(0, len(datasets), 72):
            batch = datasets[offset:offset + 72]
            batch_keys = [d["collection_key"] for d in batch]
            placeholders = ",".join(["%s"] * len(batch_keys))
            records_by_table = {table: [] for table in TABLES.values()}
            summary_records, collection_records = [], []
            for ds in batch:
                table = TABLES[ds["source_no"]]
                key = ds["collection_key"]
                timestamp = datetime.fromisoformat(ds["fetched_at"]).astimezone(timezone.utc).replace(tzinfo=None)
                month = ds["month"] + "-01"
                for r in ds["details"]:
                    identity = [key, r["source_row"], r["product_category"], r["product_name"],
                                r["country_name"], r["rejection_reason"], r["unit"]]
                    records_by_table[table].append((
                        digest(identity), key, month, ds["type_code"], ds["type_name"],
                        r["product_category"], r["product_name"], r["country_name"],
                        r["rejection_reason"], r["case_count"], r["quantity"], r["unit"],
                        r["source_row"], timestamp))
                summary_records.extend(
                    (key, r["row_index"], r["level"], r["unit"],
                     json.dumps(r["labels"], ensure_ascii=False), r["case_count"], r["quantity"])
                    for r in ds["summaries"])
                collection_records.append((
                    key, month, ds["source_no"], ds["type_code"], ds["type_name"], timestamp,
                    ds["source_url"], ds["source_file"], ds["source_sha256"], ds["detail_count"],
                    ds["summary_count"], ds["blank_category_count"],
                    json.dumps(ds["validation"], ensure_ascii=False),
                    json.dumps(ds["request"]), "COMPLETE"))
            with connection.cursor() as cur:
                # Replace only the exact requested snapshots, never other months.
                for table, records in records_by_table.items():
                    cur.execute(f"DELETE FROM {table} WHERE collection_key IN ({placeholders})", batch_keys)
                    if records:
                        cur.executemany(f"""INSERT INTO {table}
                            (record_key,collection_key,reference_month,statistics_type,statistics_type_name,
                             product_category,product_name,country_name,rejection_reason,case_count,
                             quantity,unit,source_row,collected_at)
                            VALUES ({','.join(['%s'] * 14)})""", records)
                cur.execute(f"DELETE FROM qia_statistics_summaries WHERE collection_key IN ({placeholders})", batch_keys)
                cur.executemany("""INSERT INTO qia_statistics_summaries
                    (collection_key,row_index,summary_level,unit,labels_json,case_count,quantity)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""", summary_records)
                cur.executemany("""REPLACE INTO qia_statistics_collections
                    (collection_key,reference_month,source_no,statistics_type,statistics_type_name,
                     fetched_at,source_url,source_file,source_sha256,detail_count,summary_count,
                     blank_category_count,validation_json,request_json,status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", collection_records)
                for no, table in TABLES.items():
                    cur.execute(f"""SELECT collection_key, COUNT(*), SUM(case_count)
                        FROM {table} WHERE collection_key IN ({placeholders}) GROUP BY collection_key""", batch_keys)
                    expected = {(d["collection_key"], d["detail_count"],
                                 sum(r["case_count"] for r in d["details"]))
                                for d in batch if d["source_no"] == no and d["details"]}
                    if set(cur.fetchall()) != expected:
                        raise ValueError("Database readback mismatch")
            connection.commit()
            print(f"SAVED {batch[0]['month']}..{batch[-1]['month']} "
                  f"datasets={len(batch)} rows={sum(len(r) for r in records_by_table.values())}", flush=True)
    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass  # Preserve the original failure if the server disconnected.
        raise
    finally:
        connection.close()


def load_mysql(manifest):
    import pymysql
    for attempt in range(4):
        try:
            return _load_mysql_once(manifest)
        except (pymysql.OperationalError, pymysql.InterfaceError) as exc:
            if attempt == 3 or exc.args[0] not in (0, 2006, 2013):
                raise
            print(f"DB connection interrupted; retry {attempt + 1}/3", flush=True)
            time.sleep(2 ** attempt)


def verify_mysql(manifest):
    """Read every stored detail/summary back and compare to validated originals."""
    from database.db import get_connection
    datasets = manifest["datasets"]
    expected_keys = {f"{month}:no{no}:type{type_code}"
                     for month in months_between(manifest["start"], manifest["end"])
                     for no, codes in ((2, (1, 2, 3, 4)), (4, (3, 4))) for type_code in codes}
    keys = [ds["collection_key"] for ds in datasets]
    if len(keys) != len(set(keys)) or set(keys) != expected_keys:
        raise ValueError("Manifest has missing or duplicate monthly datasets")
    placeholders = ",".join(["%s"] * len(keys))
    result = {"verified_at": datetime.now(timezone.utc).isoformat(),
              "datasets": len(keys), "detail_rows": {}, "summary_rows": 0}
    connection = get_connection()
    try:
        with connection.cursor() as cur:
            cur.execute(f"""SELECT collection_key,status,source_sha256,detail_count,summary_count
                FROM qia_statistics_collections WHERE collection_key IN ({placeholders})""", keys)
            expected = {(d["collection_key"], "COMPLETE", d["source_sha256"],
                         d["detail_count"], d["summary_count"]) for d in datasets}
            if set(cur.fetchall()) != expected:
                raise ValueError("Stored collection metadata differs from manifest")
            for no, table in TABLES.items():
                cur.execute(f"""SELECT collection_key,reference_month,statistics_type,
                    statistics_type_name,product_category,product_name,country_name,
                    rejection_reason,case_count,quantity,unit,source_row
                    FROM {table} WHERE collection_key IN ({placeholders})""", keys)
                actual = cur.fetchall()
                expected = [(d["collection_key"], date.fromisoformat(d["month"] + "-01"),
                             d["type_code"], d["type_name"], r["product_category"],
                             r["product_name"], r["country_name"], r["rejection_reason"],
                             r["case_count"], Decimal(r["quantity"]), r["unit"], r["source_row"])
                            for d in datasets if d["source_no"] == no for r in d["details"]]
                if len(actual) != len(expected) or set(actual) != set(expected):
                    raise ValueError(f"Stored detail values differ: {table}")
                result["detail_rows"][table] = len(actual)
            cur.execute(f"""SELECT collection_key,row_index,summary_level,unit,
                labels_json,case_count,quantity FROM qia_statistics_summaries
                WHERE collection_key IN ({placeholders})""", keys)
            actual = [(key, index, level, unit, tuple(json.loads(labels)), count, quantity)
                      for key, index, level, unit, labels, count, quantity in cur.fetchall()]
            expected = [(d["collection_key"], r["row_index"], r["level"], r["unit"],
                         tuple(r["labels"]), r["case_count"], Decimal(r["quantity"]))
                        for d in datasets for r in d["summaries"]]
            if len(actual) != len(expected) or set(actual) != set(expected):
                raise ValueError("Stored source summaries differ")
            result["summary_rows"] = len(actual)
    finally:
        connection.close()
    result["status"] = "VERIFIED"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-01")
    parser.add_argument("--end", default="2026-09")
    parser.add_argument("--load", action="store_true", help="Load validated snapshots into project MySQL")
    args = parser.parse_args()
    output = ROOT / "data" / "qia_statistics" / f"{args.start}_{args.end}"
    manifest = collect(args.start, args.end, output)
    if args.load:
        load_mysql(manifest)
        verification = verify_mysql(manifest)
        (output / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"datasets": manifest["dataset_count"],
                      "detail_rows": sum(d["detail_count"] for d in manifest["datasets"]),
                      "mysql_loaded": args.load, "manifest": str(output / "manifest.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
