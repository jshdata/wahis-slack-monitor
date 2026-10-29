import unittest
from slack.country_map import country_boundary


class CountryMapTests(unittest.TestCase):
    def test_report_country_and_no_neighbors(self):
        result = country_boundary(' Lithuania ')
        self.assertEqual(len(result['features']), 1)
        self.assertEqual(result['features'][0]['properties']['ISO_A3'], 'LTU')
        self.assertEqual(result['features'][0]['geometry']['type'], 'MultiPolygon')

    def test_unknown_is_not_guessed(self):
        self.assertEqual(country_boundary('Lithuani')['features'], [])
        self.assertEqual(country_boundary(None)['features'], [])

    def test_explicit_alias_and_case(self):
        result = country_boundary('UNITED STATES')
        self.assertEqual(result['features'][0]['properties']['ADMIN'], 'United States of America')
        self.assertEqual(len(result['features']), 1)
