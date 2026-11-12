import unittest

import pandas as pd

from modeling.hpai_logistic import build_panel
from modeling.rolling_logistic import features


class PanelTests(unittest.TestCase):
    def source(self):
        return pd.DataFrame({
            'outbreak_id': range(60), 'country': ['A'] * 60,
            'start_date': pd.date_range('2010-01-01', periods=60, freq='MS'),
            'disease': ['High pathogenicity avian influenza viruses (Inf. with) (poultry)'] * 60})

    def test_target_and_future_counts_do_not_change_past_features(self):
        raw = self.source()
        before, _ = build_panel(raw, pd.Period('2014-12'))
        changed = raw.copy()
        changed.loc[changed.start_date >= '2014-01-01', 'start_date'] += pd.DateOffset(months=1)
        after, _ = build_panel(changed, pd.Period('2014-12'))
        columns = ['lag1', 'lag12', 'past3', 'past6']
        pd.testing.assert_frame_equal(
            before.loc[before.month <= pd.Period('2014-01'), columns],
            after.loc[after.month <= pd.Period('2014-01'), columns])

    def test_duplicates_not_counted_twice_and_categories_combined(self):
        raw = self.source()
        extra = raw.iloc[[-1]].copy()
        extra['outbreak_id'] = 100
        extra['disease'] = 'Influenza A viruses of high pathogenicity (Inf. with) (non-poultry including wild birds) (2017-)'
        panel, _ = build_panel(pd.concat([raw, raw, extra]), pd.Period('2014-12'))
        self.assertEqual(panel.iloc[-1]['count'], 2)
        self.assertEqual(panel.iloc[-1]['lag1'], 1)

    def test_conflicting_identity_rejected(self):
        raw = self.source()
        extra = raw.iloc[[0]].copy()
        extra['country'] = 'B'
        with self.assertRaises(ValueError):
            build_panel(pd.concat([raw, extra]), pd.Period('2014-12'))

    def test_enhanced_features_only_use_lagged_values(self):
        panel, _ = build_panel(self.source(), pd.Period('2014-12'))
        original = features(panel)
        changed = panel.copy()
        changed['count'] = 9999
        changed['target'] = 1 - changed['target']
        derived = ['log_lag1', 'log_lag12', 'log_past3', 'log_past6',
                   'previous_positive', 'previous_year_positive']
        pd.testing.assert_frame_equal(original[derived], features(changed)[derived])


if __name__ == '__main__':
    unittest.main()
