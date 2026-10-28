import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from woah.restore_pdf_backup import restore


class RestoreBackupTests(unittest.TestCase):
    @patch('woah.restore_pdf_backup.pdf_storage.store_pdf')
    def test_corrupt_later_file_prevents_all_uploads(self, upload):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = b'%PDF-test'
            digest = hashlib.sha256(data).hexdigest()
            (root / f'1-{digest}.pdf').write_bytes(data)
            (root / f'2-{digest}.pdf').write_bytes(b'corrupt')
            (root / 'inventory.json').write_text(json.dumps([
                [1, 1, digest, len(data), 0, 0],
                [2, 2, digest, len(data), 0, 0]]), encoding='utf-8')
            with self.assertRaises(ValueError):
                restore(root, upload=True)
        upload.assert_not_called()

    @patch('woah.restore_pdf_backup.pdf_storage.store_pdf')
    def test_default_is_local_validation_only(self, upload):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = b'%PDF-test'
            digest = hashlib.sha256(data).hexdigest()
            (root / f'1-{digest}.pdf').write_bytes(data)
            (root / 'inventory.json').write_text(
                json.dumps([[1, 1, digest, len(data), 0, 0]]), encoding='utf-8')
            restore(root)
        upload.assert_not_called()
