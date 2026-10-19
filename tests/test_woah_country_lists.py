import json
import unittest
from unittest.mock import patch

from slack.woah_docs import countries_view, filtered_documents, list_view, register_woah_handlers


class CountryListTests(unittest.TestCase):
    def test_inclusive_optional_dates_and_unknown(self):
        docs = [{'published_date': value} for value in
                ('2025-01-01', '2026-01-01', '2026-01-31', None, 'invalid')]
        self.assertEqual(filtered_documents(docs), (docs, 0))
        selected, unknown = filtered_documents(docs, '2026-01-01', '2026-01-31')
        self.assertEqual(len(selected), 2)
        self.assertEqual(unknown, 2)
        self.assertEqual(len(filtered_documents(docs, None, '2025-01-01')[0]), 1)
        with self.assertRaises(ValueError):
            filtered_documents(docs, '2026-02-01', '2026-01-01')

    @patch('slack.woah_docs.woah_db')
    def test_all_diseases_regions_and_deduplication(self, db):
        db.list_declaration_countries.return_value = [
            dict(disease='HPAI', country=country, region=region, published_date='2026-01-01')
            for country, region in [('Japan', 'Asia'), ('Japan', 'Asia'),
                                    ('USA', 'North America'), ('Brazil', 'South America'),
                                    ('Unmapped', None)]]
        view = countries_view('all')
        rendered = json.dumps(view, ensure_ascii=False)
        for label in ('아시아', '유럽', '아프리카', '아메리카', '오세아니아', '기타'):
            self.assertIn(label, rendered)
        for disease in ('HPAI', 'ASF', 'FMD', 'LSD'):
            self.assertIn(disease, rendered)
        self.assertEqual(rendered.count('Japan'), 1)
        self.assertIn('Brazil, USA', rendered)
        self.assertIn('Unmapped', rendered)
        db.list_declaration_countries.assert_called_once_with(None)

    @patch('slack.woah_docs.woah_db')
    def test_filters_and_empty_date_defaults(self, db):
        db.list_documents.return_value = ([], None)
        db.latest_run.return_value = None
        view = list_view()
        selector = view['blocks'][1]
        self.assertEqual(selector['type'], 'section')
        self.assertEqual(selector['accessory']['type'], 'multi_static_select')
        self.assertEqual(selector['accessory']['action_id'], 'woah_docs_disease')
        self.assertEqual([option['value'] for option in selector['accessory']['initial_options']], ['HPAI'])
        dates = [e for b in view['blocks'] for e in b.get('elements', [])
                 if e.get('type') == 'datepicker']
        self.assertEqual(len(dates), 2)
        self.assertTrue(all('initial_date' not in e for e in dates))
        self.assertIn('woah_docs_countries', json.dumps(view))
        self.assertFalse(any(b['type'] == 'input' for b in view['blocks']))

    @patch('slack.woah_docs.woah_db')
    def test_long_country_lists_never_truncate(self, db):
        db.list_declaration_countries.return_value = [
            dict(disease='HPAI', country=f'Country {i:03} long name', region='Asia', published_date=None)
            for i in range(240)]
        view = countries_view()
        rendered = json.dumps(view)
        for i in range(240):
            self.assertEqual(rendered.count(f'Country {i:03} long name'), 1)
        self.assertLess(len(view['blocks']), 100)
        self.assertTrue(all(len(field['text']) <= 2000 for b in view['blocks'] for field in b.get('fields', [])))


if __name__ == '__main__':
    unittest.main()
