import io
import hashlib
import json
import unittest
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from slack_sdk.errors import SlackApiError

from pypdf import PdfWriter

from woah.collector import decode_table, disease_code, download_pdf, extract_pages, normalize_row, validate_pdf_url
from slack.woah_docs import chatgpt_view, list_view
from woah.chatgpt import SUMMARY_PROMPT, export_document
import woah_main


def source_table(complete=True):
    names = ['Self_Declaration_All.Country', 'Self_Declaration_All.Category',
             'Self_Declaration_All.Self-declared freedom from',
             'Self_Declaration_All.Date of 1st publication', 'Self_Declaration_All.Coverage',
             'Min(Self_Declaration_All.Link_EN)']
    schema = [{'N': f'G{i}', **({'DN': f'D{i}'} if i != 3 else {})} for i in range(6)]
    return {'descriptor': {'Select': [{'Name': name} for name in names]},
            'dsr': {'DS': [{'IC': complete,
             'ValueDicts': {'D0': ['Germany', 'Sweden'], 'D1': ['Terrestrial'],
                           'D2': ['High pathogenicity avian influenza viruses in poultry (infection with)'],
                           'D4': ['Member'], 'D5': ['https://www.woah.org/example.pdf']},
             'PH': [{'DM0': [
                 {'S': schema, 'C': [0, 0, 0, 1791763200000, 0, 0]},
                 {'C': [1, 'https://www.woah.org/second.pdf'], 'R': 30},
                 {'C': [], 'R': 31, 'Ø': 32},
             ]}]}]}}


class CollectorTests(unittest.TestCase):
    def test_dictionary_repeat_null_and_raw_url(self):
        rows = decode_table(source_table())
        docs = [normalize_row(row) for row in rows]
        self.assertEqual([d['country'] for d in docs], ['Germany', 'Sweden', 'Sweden'])
        self.assertEqual(docs[0]['published_date'], '2026-10-12')
        self.assertEqual(docs[1]['pdf_url'], 'https://www.woah.org/second.pdf')
        self.assertIsNone(docs[2]['pdf_url'])
        self.assertTrue(all(d['disease'] == 'HPAI' for d in docs))

    def test_incomplete_table_is_failure_not_empty_success(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            decode_table(source_table(False))

    def test_slicer_is_ignored(self):
        self.assertIsNone(decode_table({'descriptor': {'Select': [{'Name': 'Member'}]}}))

    def test_normalize_hyphenated_disease(self):
        self.assertEqual(disease_code('Foot-and-mouth disease'), 'FMD')
        self.assertEqual(disease_code('Lumpy skin disease virus (infection with)'), 'LSD')
        self.assertIsNone(disease_code('Low pathogenicity avian influenza'))

    def test_only_public_woah_https_downloads(self):
        validate_pdf_url('https://www.woah.org/app/uploads/example.pdf')
        for url in ('http://www.woah.org/a.pdf', 'https://woah.org.evil.test/a.pdf',
                    'https://127.0.0.1/a.pdf', 'https://user:pass@www.woah.org/a.pdf'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_pdf_url(url)

    def test_image_only_pdf_retains_physical_pages(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_blank_page(width=100, height=100)
        stream = io.BytesIO()
        writer.write(stream)
        self.assertEqual(extract_pages(stream.getvalue()), [{'page': 1, 'text': ''}, {'page': 2, 'text': ''}])

    @patch('woah.collector.time.sleep')
    @patch('woah.collector.requests.Session')
    def test_interrupted_download_discards_partial_bytes(self, session_factory, sleep):
        import requests
        first, second = MagicMock(), MagicMock()
        for response in (first, second):
            response.__enter__.return_value = response
            response.is_redirect = False
            response.headers = {}
        def interrupted():
            yield b'%PDF-partial'
            raise requests.exceptions.ChunkedEncodingError('connection dropped')
        first.iter_content.return_value = interrupted()
        second.iter_content.return_value = [b'%PDF-complete']
        session = session_factory.return_value
        session.get.side_effect = [first, second]
        self.assertEqual(download_pdf('https://www.woah.org/test.pdf'), b'%PDF-complete')

    @patch('woah.collector.requests.Session')
    def test_external_redirect_is_not_followed(self, session_factory):
        response = MagicMock()
        response.__enter__.return_value = response
        response.is_redirect = True
        response.headers = {'Location': 'https://example.com/a.pdf'}
        session_factory.return_value.get.return_value = response
        with self.assertRaises(ValueError):
            download_pdf('https://www.woah.org/test.pdf')
        self.assertEqual(session_factory.return_value.get.call_count, 1)


class SyncTests(unittest.TestCase):
    @patch('woah_main.sync', return_value={})
    @patch('woah_main.woah_db')
    def test_scheduled_retry_distinguishes_partial_missed_and_successful_runs(self, db, sync):
        db.latest_run.side_effect = [
            dict(status='SUCCESS', checked_at=datetime(2026, 10, 15, 0, 10)),
            dict(status='PARTIAL', checked_at=datetime(2026, 10, 15, 0, 15)),
            dict(status='NO_DOCUMENTS', checked_at=datetime(2026, 10, 15, 0, 10)),
            dict(status='SUCCESS', checked_at=datetime(2026, 10, 14, 0, 10)),
        ]
        woah_main.retry_scheduled(['ASF', 'HPAI', 'FMD', 'LSD'],
                                  datetime(2026, 10, 15, 1, tzinfo=timezone.utc))
        self.assertEqual(sync.call_count, 2)
        self.assertEqual(sync.call_args_list[0].args, (['LSD'],))
        self.assertEqual(sync.call_args_list[1].args, (['HPAI'],))
        self.assertEqual(sync.call_args_list[1].kwargs, {'retry_failed': True})

    @patch('woah_main.sync', return_value={})
    @patch('woah_main.woah_db')
    def test_failed_list_collection_requires_full_check_even_for_ready_pdfs(self, db, sync):
        db.latest_run.return_value = dict(status='COLLECTION_FAILED', checked_at=datetime(2026, 10, 15, 0, 10))
        woah_main.retry_scheduled(['HPAI'], datetime(2026, 10, 15, 1, tzinfo=timezone.utc))
        sync.assert_called_once_with(['HPAI'])

    @patch('woah_main.extract_pages', return_value=[{'page': 1, 'text': 'body'}])
    @patch('woah_main.download_pdf', return_value=b'%PDF-test')
    @patch('woah_main.woah_db')
    @patch('woah_main.discover_documents')
    def test_retry_uses_document_identity_not_shared_url(self, discover, db, download, extract):
        docs = [{'source_identity': name, 'disease': 'ASF', 'pdf_url': 'https://www.woah.org/shared.pdf'}
                for name in ('zone-a', 'zone-b')]
        discover.return_value = docs
        db.list_documents.return_value = [
            {'source_key': hashlib.sha256(doc['source_identity'].encode()).hexdigest(),
             'download_status': status} for doc, status in zip(docs, ('READY', 'DOWNLOAD_FAILED'))]
        result = woah_main.sync(['ASF'], retry_failed=True)
        self.assertEqual(result['ASF']['saved'], 1)
        self.assertEqual(result['ASF']['skipped'], 1)
        db.upsert_document.assert_called_once_with(docs[1])
        download.assert_called_once()

    @patch('woah_main.woah_db')
    @patch('woah_main.discover_documents', side_effect=RuntimeError('offline'))
    def test_source_failure_is_never_no_documents(self, discover, db):
        with self.assertRaises(RuntimeError):
            woah_main.sync(['ASF', 'FMD'])
        self.assertEqual([call.args[1] for call in db.record_run.call_args_list],
                         ['COLLECTION_FAILED', 'COLLECTION_FAILED'])
        db.upsert_document.assert_not_called()

    @patch('woah_main.woah_db')
    @patch('woah_main.discover_documents', return_value=[])
    def test_verified_absence_has_separate_state(self, discover, db):
        result = woah_main.sync(['FMD'])
        self.assertEqual(result['FMD']['status'], 'NO_DOCUMENTS')

    @patch('woah_main.download_pdf', side_effect=RuntimeError('download failed'))
    @patch('woah_main.woah_db')
    @patch('woah_main.discover_documents')
    def test_failed_download_preserves_prior_pdf(self, discover, db, download):
        discover.return_value = [{'source_identity': 'row1', 'disease': 'ASF', 'pdf_url': 'https://www.woah.org/example.pdf'}]
        db.upsert_document.return_value = 15
        result = woah_main.sync(['ASF'])
        self.assertEqual(result['ASF']['status'], 'PARTIAL')
        db.download_failed.assert_called_once()
        db.save_pdf.assert_not_called()


class SlackViewTests(unittest.TestCase):
    @patch('slack.woah_docs.POOL')
    def test_rejected_view_replaces_loading_and_logs_slack_reason(self, pool):
        from slack.woah_docs import submit, modal, section
        client = MagicMock()
        client.views_update.side_effect = [SlackApiError('rejected',
            {'error': 'invalid_blocks', 'response_metadata': {'messages': ['invalid block']}}), {}]
        with self.assertLogs('slack.woah_docs', level='INFO') as logs:
            submit(client, 'V123', lambda: modal([section('documents')]))
            pool.submit.call_args.args[0]()
        self.assertEqual(client.views_update.call_count, 2)
        self.assertIn('표시하지 못했습니다', str(client.views_update.call_args.kwargs['view']))
        self.assertIn('invalid_blocks', '\n'.join(logs.output))

    @patch('slack.woah_docs.woah_db')
    def test_manual_view_provides_prompt_and_links_without_api(self, db):
        db.get_document.return_value = dict(country='Germany', disease='HPAI', title='Declaration',
                                            latest_version_id=20, pdf_url='https://www.woah.org/a.pdf')
        with patch.dict('sys.modules', {'openai': None}):
            view = chatgpt_view(20, 'HPAI', 0)
        blocks = view['blocks']
        text = '\n'.join(b['text']['text'] for b in blocks if b['type'] == 'section')
        self.assertIn(SUMMARY_PROMPT, text)
        self.assertIn('자동 전송되지 않습니다', text)
        urls = [e['url'] for b in blocks if b['type'] == 'actions' for e in b['elements'] if 'url' in e]
        self.assertEqual(urls, ['https://www.woah.org/a.pdf', 'https://chatgpt.com/'])
        db.get_document.assert_called_once_with(20)

    @patch('slack.woah_docs.woah_db')
    def test_paginated_list_does_not_embed_pdf_bytes(self, db):
        db.latest_run.return_value = None
        db.list_documents.return_value = ([dict(
            id=i, disease='HPAI', country=f'Country {i}', title='Declaration',
            published_date='2026-10-12', download_status='READY', page_count=10,
            latest_version_id=i + 1, pdf_url='https://www.woah.org/a.pdf') for i in range(25)], None)
        view = list_view('HPAI', 1)
        text = json.dumps(view)
        self.assertIn('Country 8', text)
        self.assertNotIn('Country 0', text)
        self.assertLess(len(view['blocks']), 100)
        self.assertNotIn('pdf_data', text)
        self.assertTrue(all(len(b['text']['text']) < 3000 for b in view['blocks'] if b['type'] == 'section'))

    @patch('slack.woah_docs.woah_db')
    def test_no_documents_and_failed_collection_have_distinct_messages(self, db):
        db.list_documents.return_value = []
        db.latest_run.return_value = dict(status='COLLECTION_FAILED', checked_at='2026-10-15',
                                         found_count=0, saved_count=0, failed_count=0)
        db.list_documents.side_effect = lambda *args, **kwargs: ([], db.latest_run.return_value)
        failed = json.dumps(list_view('FMD'), ensure_ascii=False)
        self.assertIn('최신 목록 수집에 실패', failed)
        self.assertNotIn('공개 문서를 찾지 못했습니다', failed)
        db.latest_run.return_value['status'] = 'NO_DOCUMENTS'
        self.assertIn('공개 문서를 찾지 못했습니다', json.dumps(list_view('FMD'), ensure_ascii=False))


class ExportTests(unittest.TestCase):
    @patch('woah.chatgpt.woah_db.get_document')
    def test_export_preserves_original_pdf_and_creates_prompt(self, get):
        get.return_value = {'latest_version_id': 25, 'pdf_data': b'%PDF-original'}
        with tempfile.TemporaryDirectory() as directory:
            pdf, prompt = export_document(20, directory)
            self.assertEqual(pdf.read_bytes(), b'%PDF-original')
            self.assertEqual(prompt.read_text(encoding='utf-8'), SUMMARY_PROMPT)
            self.assertEqual(export_document(20, directory), (pdf, prompt))
        get.assert_called_with(20, include_pdf=True)

    @patch('woah.chatgpt.woah_db.get_document')
    def test_export_does_not_overwrite_user_edits(self, get):
        get.return_value = {'latest_version_id': 25, 'pdf_data': b'%PDF-original'}
        with tempfile.TemporaryDirectory() as directory:
            pdf, prompt = export_document(20, directory)
            prompt.write_text('My edited prompt', encoding='utf-8')
            with self.assertRaises(ValueError):
                export_document(20, directory)
            self.assertEqual(prompt.read_text(encoding='utf-8'), 'My edited prompt')
            self.assertEqual(pdf.read_bytes(), b'%PDF-original')


if __name__ == '__main__':
    unittest.main()
