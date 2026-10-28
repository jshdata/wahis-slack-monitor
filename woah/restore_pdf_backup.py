"""Upload a verified local inventory without modifying the database or backup."""
import argparse
import hashlib
import json
from pathlib import Path

from dotenv import load_dotenv
from woah import pdf_storage


def restore(directory, upload=False):
    inventory = json.loads((directory / 'inventory.json').read_text(encoding='utf-8'))
    # Validate every source before starting any remote writes.
    sources = []
    for version_id, document_id, digest, size, *_ in inventory:
        path = directory / f'{version_id}-{digest}.pdf'
        data = path.read_bytes()
        if (len(data) != size or hashlib.sha256(data).hexdigest() != digest
                or not data.startswith(b'%PDF-')):
            raise ValueError(f'Invalid PDF backup: version {version_id}')
        sources.append((version_id, path, digest))
    print(f'Local inventory verified: {len(sources)} versions', flush=True)
    if upload:
        if not pdf_storage.enabled():
            raise ValueError('External storage must be enabled')
        for version_id, path, digest in sources:
            if pdf_storage.store_pdf(path.read_bytes()) != digest:
                raise ValueError(f'Upload digest mismatch: version {version_id}')
            print(f'Version {version_id}: uploaded and readback verified', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--upload', action='store_true')
    args = parser.parse_args()
    load_dotenv('.env')
    restore(args.directory, args.upload)
