"""Additive MySQL tables. PDF bytes are never loaded by list queries."""
import hashlib
import json
from contextlib import contextmanager

import pymysql

from database.db import get_connection
from woah import pdf_storage

DDL = [
    """CREATE TABLE IF NOT EXISTS woah_documents (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        source_key CHAR(64) NOT NULL UNIQUE,
        disease VARCHAR(20) NOT NULL,
        country VARCHAR(200) NOT NULL,
        title TEXT NOT NULL,
        published_date VARCHAR(100) NULL,
        declaration_status VARCHAR(200) NULL,
        source_metadata JSON NOT NULL,
        pdf_url TEXT NULL,
        download_status VARCHAR(30) NOT NULL,
        last_error TEXT NULL,
        latest_version_id BIGINT NULL,
        first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_download_at DATETIME NULL,
        INDEX idx_woah_disease_country (disease, country)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS woah_document_versions (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        document_id BIGINT NOT NULL,
        sha256 CHAR(64) NOT NULL,
        pdf_data LONGBLOB NOT NULL,
        byte_size BIGINT NOT NULL,
        page_count INT NOT NULL,
        pages_json JSON NOT NULL,
        extraction_status VARCHAR(30) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_woah_document_hash (document_id, sha256),
        FOREIGN KEY (document_id) REFERENCES woah_documents(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS woah_collection_runs (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        disease VARCHAR(20) NOT NULL,
        status VARCHAR(30) NOT NULL,
        found_count INT NOT NULL,
        saved_count INT NOT NULL,
        failed_count INT NOT NULL,
        error TEXT NULL,
        checked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_woah_run (disease, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


@contextmanager
def connection():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET time_zone = '+00:00'")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema():
    with connection() as conn, conn.cursor() as cur:
        for statement in DDL:
            cur.execute(statement)


def upsert_document(doc):
    # The source list's stable row identity includes country, scope and language.
    key = hashlib.sha256(doc['source_identity'].encode('utf-8')).hexdigest()
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO woah_documents
            (source_key,disease,country,title,published_date,declaration_status,
             source_metadata,pdf_url,download_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), title=VALUES(title),
            published_date=VALUES(published_date), declaration_status=VALUES(declaration_status),
            source_metadata=VALUES(source_metadata), pdf_url=VALUES(pdf_url),
            last_seen_at=CURRENT_TIMESTAMP""",
            (key, doc['disease'], doc['country'], doc['title'], doc.get('published_date'),
             doc.get('status'), json.dumps(doc['metadata'], ensure_ascii=False),
             doc.get('pdf_url'), 'PENDING' if doc.get('pdf_url') else 'NO_PDF_LINK'))
        return cur.lastrowid


def save_pdf(document_id, pdf, pages):
    digest = hashlib.sha256(pdf).hexdigest()
    # Empty bytes mark an R2 object at woah/pdf/<sha256>.pdf. Existing blobs
    # remain readable without R2, allowing a staged deployment and migration.
    stored_pdf = pdf
    if pdf_storage.enabled():
        pdf_storage.store_pdf(pdf)
        stored_pdf = b''
    with connection() as conn, conn.cursor() as cur:
        cur.execute('SELECT @@max_allowed_packet')
        packet = cur.fetchone()[0]
        # PyMySQL escapes bytes in SQL; leave room for escaping and page text.
        if len(stored_pdf) * 2 + len(json.dumps(pages).encode()) + 65536 > packet:
            raise ValueError('PDF exceeds MySQL max_allowed_packet; increase the server setting')
        cur.execute("""INSERT INTO woah_document_versions
            (document_id,sha256,pdf_data,byte_size,page_count,pages_json,extraction_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)""",
            (document_id, digest, stored_pdf, len(pdf), len(pages), json.dumps(pages),
             'TEXT' if any(p['text'].strip() for p in pages) else 'IMAGE_ONLY'))
        version_id = cur.lastrowid
        cur.execute("""UPDATE woah_documents SET latest_version_id=%s,
            download_status='READY',last_error=NULL,last_download_at=CURRENT_TIMESTAMP
            WHERE id=%s""", (version_id, document_id))
        return version_id


def download_failed(document_id, error, status='DOWNLOAD_FAILED'):
    with connection() as conn, conn.cursor() as cur:
        cur.execute('UPDATE woah_documents SET download_status=%s,last_error=%s WHERE id=%s',
                    (status, str(error)[:2000], document_id))


def record_run(disease, status, found=0, saved=0, failed=0, error=None):
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO woah_collection_runs
            (disease,status,found_count,saved_count,failed_count,error)
            VALUES (%s,%s,%s,%s,%s,%s)""", (disease,status,found,saved,failed,error))


def list_documents(disease=None):
    with connection() as conn, conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute("""SELECT d.id,d.source_key,d.disease,d.country,d.title,d.published_date,
            d.declaration_status,d.download_status,d.last_seen_at,d.pdf_url,
            d.latest_version_id,v.page_count,v.byte_size
            FROM woah_documents d LEFT JOIN woah_document_versions v ON v.id=d.latest_version_id
            WHERE (%s IS NULL OR d.disease=%s) ORDER BY d.country,d.id""", (disease,disease))
        return cur.fetchall()


def latest_run(disease):
    with connection() as conn, conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute('SELECT * FROM woah_collection_runs WHERE disease=%s ORDER BY id DESC LIMIT 1', (disease,))
        return cur.fetchone()


def list_declaration_countries(disease=None):
    """Metadata only; join with explicit collation for the existing MySQL tables."""
    with connection() as conn, conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute("""SELECT DISTINCT d.disease,d.country,d.published_date,
            d.declaration_status,cr.region
            FROM woah_documents d LEFT JOIN country_regions cr
              ON (CASE WHEN TRIM(d.country) IN ('Türkiye','Turkey')
                       THEN 'Türkiye (Rep. of)' ELSE TRIM(d.country) END) COLLATE utf8mb4_unicode_ci
               = TRIM(cr.country) COLLATE utf8mb4_unicode_ci
            WHERE (%s IS NULL OR d.disease=%s)
            ORDER BY d.disease,d.country,d.published_date""", (disease, disease))
        return cur.fetchall()


def get_document(document_id, include_pdf=False):
    columns = ',v.pdf_data,v.sha256' if include_pdf else ''
    with connection() as conn, conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute("""SELECT d.*,v.page_count,v.pages_json,v.extraction_status""" + columns + """
            FROM woah_documents d LEFT JOIN woah_document_versions v ON v.id=d.latest_version_id
            WHERE d.id=%s""", (document_id,))
        doc = cur.fetchone()
    if include_pdf and doc and doc.get('sha256') and not doc.get('pdf_data'):
        doc['pdf_data'] = pdf_storage.read_pdf(doc['sha256'])
    return doc
