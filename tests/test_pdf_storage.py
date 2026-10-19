import hashlib
import io
import unittest
from unittest.mock import patch

from woah import pdf_storage, migrate_pdfs
from database import woah_db


class PdfStorageTests(unittest.TestCase):
    @patch('database.woah_db.time.monotonic')
    @patch('database.woah_db.connection')
    def test_overview_reuses_metadata_and_refreshes_after_expiry(self, connection, clock):
        with patch.dict(woah_db._overview_cache, {}, clear=True):
            clock.return_value = 100
            cursor = connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = [{'id': 1}]
            cursor.fetchone.return_value = {'status': 'SUCCESS'}
            first = woah_db.list_documents('HPAI', include_run=True)
            first[0][0]['id'] = 999
            self.assertEqual(woah_db.list_documents('HPAI', include_run=True)[0][0]['id'], 1)
            self.assertEqual(connection.call_count, 1)
            self.assertEqual(cursor.execute.call_count, 2)
            self.assertNotIn('pdf_data', cursor.execute.call_args_list[0].args[0])
            clock.return_value = 131
            woah_db.list_documents('HPAI', include_run=True)
            self.assertEqual(connection.call_count, 2)

    @patch('boto3.client')
    def test_railway_client_uses_s3_credentials_and_virtual_urls(self, factory):
        settings = {'WOAH_PDF_STORAGE': 'railway',
                    'S3_ENDPOINT_URL': 'https://t3.storageapi.dev',
                    'S3_BUCKET': 'private-bucket', 'S3_REGION': 'auto',
                    'S3_ACCESS_KEY_ID': 'test-id', 'S3_SECRET_ACCESS_KEY': 'test-secret'}
        with patch.dict('os.environ', settings, clear=True):
            self.assertTrue(pdf_storage.enabled())
            self.assertEqual(pdf_storage.bucket(), 'private-bucket')
            pdf_storage.client()
        options = factory.call_args.kwargs
        self.assertEqual(options['endpoint_url'], settings['S3_ENDPOINT_URL'])
        self.assertEqual(options['aws_access_key_id'], 'test-id')
        self.assertEqual(options['config'].s3['addressing_style'], 'virtual')

    @patch('woah.pdf_storage.client')
    def test_read_rejects_corruption(self, client):
        body = io.BytesIO(b'wrong')
        client.return_value.get_object.return_value = {'Body': body}
        with patch.dict('os.environ', {'WOAH_PDF_STORAGE': 'r2', 'R2_BUCKET': 'private'}):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                pdf_storage.read_pdf(hashlib.sha256(b'original').hexdigest())
        self.assertTrue(body.closed)

    @patch('woah.pdf_storage.read_pdf', side_effect=ValueError('checksum'))
    @patch('woah.pdf_storage.client')
    def test_upload_requires_readback(self, client, read):
        with patch.dict('os.environ', {'WOAH_PDF_STORAGE': 'r2', 'R2_BUCKET': 'private'}):
            with self.assertRaises(ValueError):
                pdf_storage.store_pdf(b'pdf')
        client.return_value.put_object.assert_called_once()

    @patch('woah.migrate_pdfs.pdf_storage.store_pdf', side_effect=ValueError('checksum'))
    @patch('woah.migrate_pdfs.read_version')
    @patch('woah.migrate_pdfs.connection')
    def test_failed_verification_never_removes_db_copy(self, connection, read, store):
        cursor = connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(1,)]
        read.return_value = (hashlib.sha256(b'pdf').hexdigest(), b'pdf')
        with self.assertRaises(ValueError):
            migrate_pdfs.migrate(remove_db_copies=True)
        self.assertFalse(any('UPDATE' in call.args[0] for call in cursor.execute.call_args_list))

    @patch('database.woah_db.pdf_storage.read_pdf', return_value=b'pdf')
    @patch('database.woah_db.connection')
    def test_external_document_preserves_export_interface(self, connection, read):
        cursor = connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {'pdf_data': b'', 'sha256': 'a' * 64}
        self.assertEqual(woah_db.get_document(1, include_pdf=True)['pdf_data'], b'pdf')
        read.assert_called_once_with('a' * 64)

    @patch('database.woah_db.pdf_storage.read_pdf')
    @patch('database.woah_db.connection')
    def test_existing_blob_does_not_require_r2(self, connection, read):
        cursor = connection.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {'pdf_data': b'pdf', 'sha256': 'a' * 64}
        self.assertEqual(woah_db.get_document(1, include_pdf=True)['pdf_data'], b'pdf')
        read.assert_not_called()
