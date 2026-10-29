import unittest
from unittest.mock import patch
from database.report_quantitative_dashboard import FIELDS, quantity_summary, format_quantity, species_quantities


def row(name, **values):
    return dict(species_name=name, is_wild=1, unit='Animal', data_type='new',
                **{field: values.get(field) for field in FIELDS})


class QuantitativeDashboardTests(unittest.TestCase):
    def test_missing_zero_and_partial_sum_are_distinct(self):
        summary = quantity_summary([row('Birds', cases=3, deaths=0), row('Swan', deaths=0)])
        self.assertEqual(format_quantity(summary['cases']), '3 (일부 미보고)')
        self.assertEqual(format_quantity(summary['deaths']), '0')
        self.assertEqual(format_quantity(summary['killed']), '미보고')

    def test_species_and_category_groups_do_not_mix(self):
        a, b = row('Birds', cases=2), row('Birds', cases=3)
        b['is_wild'] = 0
        table, comparisons = species_quantities([a, b])
        self.assertEqual(len(table), 2)
        self.assertEqual(sum(r['수량'] for r in comparisons), 5)

    def test_scope_unit_selection_and_species_comparison_screen(self):
        from streamlit.testing.v1 import AppTest
        rows = [row('Birds', cases=3, deaths=1), row('Swan', cases=2, deaths=2)]
        total = row('Birds', cases=20)
        total['data_type'] = 'total'
        other_unit = row('Birds', cases=500)
        other_unit['unit'] = 'Other unit'
        rows += [total, other_unit]
        app = AppTest.from_string('from slack.report_quantitative_view import render_quantities\nrender_quantities(100)',
                                  default_timeout=15)
        with patch('slack.report_quantitative_view.load_report_quantities', return_value=rows):
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(next(m.value for m in app.metric if m.label == '감염'), '5')
            self.assertEqual(len(app.dataframe[0].value), 2)
            app.selectbox[0].set_value('Other unit').run()
            self.assertEqual(next(m.value for m in app.metric if m.label == '감염'), '500')
            app.radio[0].set_value('누계').run()
            self.assertEqual(next(m.value for m in app.metric if m.label == '감염'), '20')
            self.assertEqual(len(app.exception), 0)
