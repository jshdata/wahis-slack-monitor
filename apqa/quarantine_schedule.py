"""Daily KST polling of monthly QIA releases, beginning on the 11th."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apqa.quarantine_statistics import (ROOT, SourceNotReady, collect, load_mysql,
                                       months_between, verify_mysql)
from database.db import get_connection

PAIRS = ((2, 1), (2, 2), (2, 3), (2, 4), (4, 3), (4, 4))
START = "2020-01"


def eligible_through(today):
    previous = today.replace(day=1) - timedelta(days=1)
    if today.day < 11:
        previous = previous.replace(day=1) - timedelta(days=1)
    return previous.strftime("%Y-%m")


def pending_months(today, completed):
    cutoff = eligible_through(today)
    if cutoff < START:
        return []
    return [month for month in months_between(START, cutoff)
            if not all(f"{month}:no{no}:type{t}" in completed for no, t in PAIRS)]


def ensure_attempt_schema():
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""CREATE TABLE IF NOT EXISTS qia_statistics_schedule_attempts (
                reference_month DATE NOT NULL, attempted_on DATE NOT NULL,
                status VARCHAR(20) NOT NULL, started_at DATETIME NOT NULL,
                finished_at DATETIME NULL, next_retry_on DATE NULL,
                error_type VARCHAR(100) NULL, result_json JSON NULL,
                PRIMARY KEY(reference_month, attempted_on)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        connection.commit()
    finally:
        connection.close()


def completed_keys():
    import pymysql
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""SELECT collection_key FROM qia_statistics_collections
                WHERE status='COMPLETE' AND reference_month >= '2020-01-01'
                  AND ((source_no=2 AND statistics_type IN (1,2,3,4))
                    OR (source_no=4 AND statistics_type IN (3,4)))""")
            keys = {row[0] for row in cursor.fetchall()}
            try:
                cursor.execute("""SELECT a.reference_month,a.status
                    FROM qia_statistics_schedule_attempts a
                    JOIN (SELECT reference_month,MAX(attempted_on) AS latest
                          FROM qia_statistics_schedule_attempts GROUP BY reference_month) b
                      ON a.reference_month=b.reference_month AND a.attempted_on=b.latest""")
                blocked = {month.strftime("%Y-%m") for month, status in cursor.fetchall()
                           if status != "COMPLETE"}
                # Includes a process that died after committing data but before
                # full readback. It must not be mistaken for a verified release.
                keys = {key for key in keys if key[:7] not in blocked}
            except pymysql.err.ProgrammingError as error:
                if error.args[0] != 1146:  # First run: attempts table does not exist yet.
                    raise
            return keys
    finally:
        connection.close()


def claim_attempt(month, today):
    """Persistent daily claim also prevents concurrent/manual duplicate polling."""
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT IGNORE INTO qia_statistics_schedule_attempts
                (reference_month,attempted_on,status,started_at)
                VALUES (%s,%s,'RUNNING',%s)""",
                (month + "-01", today, datetime.now(timezone.utc).replace(tzinfo=None)))
            claimed = cursor.rowcount == 1
        connection.commit()
        return claimed
    finally:
        connection.close()


def finish_attempt(month, today, status, result=None, error_type=None):
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""UPDATE qia_statistics_schedule_attempts SET
                status=%s,finished_at=%s,next_retry_on=%s,error_type=%s,result_json=%s
                WHERE reference_month=%s AND attempted_on=%s""",
                (status, datetime.now(timezone.utc).replace(tzinfo=None),
                 None if status == "COMPLETE" else today + timedelta(days=1), error_type,
                 json.dumps(result or {}, ensure_ascii=False), month + "-01", today))
        connection.commit()
    finally:
        connection.close()


def validate_release(manifest):
    datasets = manifest["datasets"]
    if len(datasets) != 6 or {(d["source_no"], d["type_code"]) for d in datasets} != set(PAIRS):
        raise ValueError("A monthly release must contain all six distinct datasets")
    # A zero-only No2 response is not proof that the monthly statistics were
    # published. No4 may legitimately contain explicit validated zero totals.
    for ds in datasets:
        if ds["source_no"] == 2 and not sum(r["case_count"] for r in ds["details"]):
            raise SourceNotReady("No2 has no positive cases; publication is not confirmed")


def run_daily(now=None, dry_run=False, max_months=3):
    if max_months < 1:
        raise ValueError("max_months must be positive")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    today = now.astimezone(ZoneInfo("Asia/Seoul")).date()
    pending = pending_months(today, completed_keys())
    result = {"checked_on": today.isoformat(), "eligible_through": eligible_through(today),
              "pending_months": pending, "results": [], "dry_run": dry_run}
    if dry_run or not pending:
        return result
    ensure_attempt_schema()
    for month in pending[:max_months]:
        if not claim_attempt(month, today):
            result["results"].append({"month": month, "status": "ALREADY_ATTEMPTED_TODAY"})
            continue
        folder = ROOT / "data" / "qia_statistics" / "scheduled" / today.isoformat() / month
        try:
            # A new dated directory prevents yesterday's unpublished response
            # from being reused by the collector's normal download cache.
            manifest = collect(month, month, folder)
            validate_release(manifest)
            load_mysql(manifest)
            verification = verify_mysql(manifest)
            (folder / "verification.json").write_text(
                json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
            finish_attempt(month, today, "COMPLETE", verification)
            result["results"].append({"month": month, "status": "COMPLETE", "verification": verification})
        except SourceNotReady as error:
            finish_attempt(month, today, "PENDING", error_type=type(error).__name__)
            result["results"].append({"month": month, "status": "PENDING", "next_retry_on": (today + timedelta(days=1)).isoformat()})
        except Exception as error:
            finish_attempt(month, today, "FAILED", error_type=type(error).__name__)
            result["results"].append({"month": month, "status": "FAILED", "error_type": type(error).__name__})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Read DB coverage only; do not poll or write")
    parser.add_argument("--max-months", type=int, default=3, help="Catch up at most this many missing months per day")
    args = parser.parse_args()
    result = run_daily(dry_run=args.dry_run, max_months=args.max_months)
    output = ROOT / "data" / "qia_statistics" / "scheduled"
    output.mkdir(parents=True, exist_ok=True)
    (output / "latest_run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if any(item["status"] == "FAILED" for item in result["results"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
