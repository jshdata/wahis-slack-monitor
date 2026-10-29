import unittest
from unittest.mock import patch
from database.report_species_dashboard import summarize_species, load_report_species


def row(oid, name, wild, loaded=100, version=100):
    return dict(outbreak_id=oid, species_name=name, is_wild=wild,
                species_loaded_report_id=loaded, species_report_id=version)


class ReportSpeciesDashboardTests(unittest.TestCase):
    def test_unique_sites_species_and_exclusive_mixed_category(self):
        result = summarize_species([row(1, 'Birds', 0), row(1, 'Birds', 0),
                                   row(2, 'Birds', 0), row(2, 'Swan', 1)], 100)
        self.assertEqual(result['categories'], {'사육': 1, '야생': 0, '혼합': 1, '미확인': 0})
        self.assertEqual(result['species'], [{'축종': 'Birds', '발생지 수': 2}, {'축종': 'Swan', '발생지 수': 1}])

    def test_unloaded_stale_and_partial_unknown(self):
        result = summarize_species([row(1, 'Cattle', 0, loaded=101),
                                   row(2, 'Birds', 0), row(2, 'Duck', None),
                                   row(3, None, None, loaded=None, version=None)], 100)
        self.assertEqual(result['categories']['미확인'], 3)
        self.assertEqual(result['sites'][1]['species'], '미확인')
        self.assertNotIn('Cattle', str(result['species']))

    @patch('database.report_species_dashboard.get_connection')
    def test_report_scoped_query_and_connection_closure(self, connect):
        cur = connect.return_value.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [row(1, 'Swan', 1)]
        self.assertEqual(load_report_species(100)['categories']['야생'], 1)
        self.assertEqual(cur.execute.call_args.args[1], (100, 100, 100))
        connect.return_value.close.assert_called_once()
