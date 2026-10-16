"""Import WAHIS animal population exports without losing the source values."""
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from database.db import get_connection
import pymysql


SOURCE_URL = 'https://wahis.woah.org/#/dashboards/animal-population-dashboard'
TEXT_FIELDS = {
    'report_id': 'Report ID',
    'country': 'Country/Territory',
    'country_iso3': 'Country(ISO3)',
    'year': 'Year',
    'animal_type': 'Animal type',
    'animal_category': 'Animal category',
    'animal_subcategory': 'Animal subcategory',
    'measuring_unit': 'Measuring unit',
}
NUMBER_FIELDS = {
    'live_animals': 'Nb live animals',
    'slaughtered_animals': 'Nb slaughtered animals',
    'animal_premises': 'Nb animals premises',
    'mean_live_weight_kg': 'Mean live weight (kg)',
    'total_meat_weight_tonnes': 'Total meat weight of slaughtered animals (tonnes)',
}


def clean(value):
    value = value.strip().strip('"').strip()
    return None if value in ('', '-') else value


def read_export(path):
    records = []
    seen = set()
    with Path(path).open(encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file)
        required = set(TEXT_FIELDS.values()) | set(NUMBER_FIELDS.values())
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Population CSV is missing required columns')
        for raw in reader:
            record = {key: clean(raw[column]) for key, column in TEXT_FIELDS.items()}
            record['year'] = int(record['year'])
            for key, column in NUMBER_FIELDS.items():
                value = clean(raw[column])
                record[key] = Decimal(value.replace(',', '.')) if value is not None else None
                if record[key] is not None and not record[key].is_finite():
                    raise ValueError(f'Invalid numeric value: {column}')
            identity = [record[key] for key in TEXT_FIELDS if key != 'country']
            record['source_key'] = hashlib.sha256(
                json.dumps(identity, ensure_ascii=False).encode('utf-8')
            ).hexdigest()
            if record['source_key'] in seen:
                raise ValueError('Duplicate population record identity')
            seen.add(record['source_key'])
            record['raw_data'] = json.dumps(raw, ensure_ascii=False)
            records.append(record)
    if not records:
        raise ValueError('Population CSV is empty')
    return records


def import_export(path):
    records = read_export(path)
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    columns = ['source_key', *TEXT_FIELDS, *NUMBER_FIELDS, 'raw_data']
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS wahis_animal_population (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                source_key CHAR(64) NOT NULL UNIQUE,
                report_id VARCHAR(64) NOT NULL,
                country VARCHAR(200) NOT NULL,
                country_iso3 CHAR(3) NOT NULL,
                year SMALLINT NOT NULL,
                animal_type VARCHAR(100) NOT NULL,
                animal_category VARCHAR(200) NOT NULL,
                animal_subcategory VARCHAR(250) NULL,
                measuring_unit VARCHAR(100) NULL,
                live_animals DECIMAL(30,6) NULL,
                slaughtered_animals DECIMAL(30,6) NULL,
                animal_premises DECIMAL(30,6) NULL,
                mean_live_weight_kg DECIMAL(30,6) NULL,
                total_meat_weight_tonnes DECIMAL(30,6) NULL,
                raw_data JSON NOT NULL,
                source_url VARCHAR(255) NOT NULL,
                source_file_sha256 CHAR(64) NOT NULL,
                imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_population_country_year (country_iso3, year),
                INDEX idx_population_category_year (animal_category, year)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
            insert_columns = columns + ['source_url', 'source_file_sha256']
            sql = ('INSERT INTO wahis_animal_population (' + ','.join(insert_columns)
                   + ') VALUES (' + ','.join(['%s'] * len(insert_columns))
                   + ') ON DUPLICATE KEY UPDATE '
                   + ','.join(f'{col}=VALUES({col})' for col in insert_columns if col != 'source_key')
                   + ',imported_at=CURRENT_TIMESTAMP')
            values = [tuple(record[col] for col in columns) + (SOURCE_URL, digest)
                      for record in records]
            for start in range(0, len(values), 500):
                cur.executemany(sql, values[start:start + 500])
            cur.execute('SELECT COUNT(*) FROM wahis_animal_population WHERE source_file_sha256=%s', (digest,))
            saved = cur.fetchone()[0]
            if saved != len(records):
                raise ValueError(f'Import verification failed: {saved} != {len(records)}')
        conn.commit()
        return {'source_rows': len(records), 'saved_rows': saved, 'source_sha256': digest}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def population_regions():
    """WAHIS dashboard regions, which differ from the outbreak region mapping."""
    path = Path(__file__).resolve().parents[1] / 'wahis' / 'population_regions.json'
    return json.loads(path.read_text(encoding='utf-8'))


def load_population_options():
    data = load_population()
    options = {field: sorted({row[field] for row in data['rows']})
               for field in ('country', 'animal_type', 'animal_category')}
    options['region'] = sorted({region for row in data['rows'] for region in row['region'].split(' / ')})
    return options


def load_population(regions=(), countries=(), animal_types=(), animal_categories=()):
    mapping = population_regions()
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute('SELECT DISTINCT year FROM wahis_animal_population ORDER BY year')
            years = [row['year'] for row in cur.fetchall()]
            if not years:
                raise ValueError('저장된 동물 개체수 자료가 없습니다.')
            conditions, params = [], []
            for column, values in (('country', countries), ('animal_type', animal_types),
                                   ('animal_category', animal_categories)):
                values = list(dict.fromkeys(values))
                if values:
                    conditions.append(f'{column} IN ({",".join(["%s"] * len(values))})')
                    params.extend(values)
            where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
            cur.execute('SELECT report_id,country,country_iso3,year,animal_type,animal_category,'
                        'animal_subcategory,measuring_unit,live_animals,animal_premises,'
                        'total_meat_weight_tonnes,imported_at FROM wahis_animal_population' + where,
                        params)
            rows = list(cur.fetchall())
        for row in rows:
            row['region'] = ' / '.join(mapping.get(row['country_iso3'], ['Unknown']))
        if regions:
            rows = [row for row in rows if set(row['region'].split(' / ')).intersection(regions)]
        return {'years': years, 'rows': rows}
    finally:
        conn.close()
