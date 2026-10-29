"""Safe CSV export and validation of map selection payloads."""
import csv
import io


def selected_outbreak(event, valid_ids):
    objects = (event or {}).get('selection', {}).get('objects', {}).get('report-outbreaks', [])
    if not objects:
        return None
    try:
        oid = int(objects[0]['outbreak_id'])
    except (ValueError, TypeError, KeyError):
        return None
    return oid if oid in valid_ids else None


def csv_bytes(rows, metadata=None):
    """UTF-8 BOM for Excel; retain zero/missing and neutralize text formulas."""
    data = [{**(metadata or {}), **row} for row in rows]
    columns = list(dict.fromkeys(key for row in data for key in row))
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for row in data:
        cleaned = {}
        for key, value in row.items():
            if value is None:
                value = '미보고'
            if isinstance(value, str) and (value.lstrip().startswith(('=', '+', '-', '@')) or
                                           value.startswith(('\t', '\r', '\n'))):
                value = "'" + value
            cleaned[key] = value
        writer.writerow(cleaned)
    return stream.getvalue().encode('utf-8-sig')
