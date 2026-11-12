"""Exploratory snapshot backtest; not an operational disease forecast."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             confusion_matrix, precision_score, recall_score,
                             roc_auc_score, f1_score)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def build_panel(raw, end):
    # Combine both HPAI source categories; no domestic/wild features or filters.
    selected = raw.disease.str.contains(
        'High pathogenicity avian influenza|Influenza A viruses of high pathogenicity',
        case=False, na=False)
    d = raw.loc[selected, ['outbreak_id', 'country', 'start_date']].copy()
    if d.isna().any().any():
        raise ValueError('Missing HPAI identity, country or date')
    d['month'] = pd.to_datetime(d.start_date, errors='raise').dt.to_period('M')
    if d.groupby('outbreak_id')[['country', 'month']].nunique().gt(1).any().any():
        raise ValueError('Conflicting outbreak identities')
    d = d.drop_duplicates('outbreak_id')
    d = d[d.month <= end]
    months = pd.period_range(d.month.min(), end, freq='M')
    if len(months) < 48:
        raise ValueError('At least 48 months required')
    # Country universe frozen before validation/test; zeros remain assumptions.
    cutoff = months[12 + int((len(months) - 12) * .6)]
    countries = sorted(d.loc[d.month < cutoff, 'country'].unique())
    index = pd.MultiIndex.from_product([countries, months], names=['country', 'month'])
    counts = d.groupby(['country', 'month']).size().reindex(index, fill_value=0)
    panel = counts.rename('count').reset_index()
    g = panel.groupby('country')['count']
    # Row month is target month: every count feature strictly precedes it.
    panel['lag1'] = g.shift(1)
    panel['lag12'] = g.shift(12)
    for window in (3, 6):
        panel[f'past{window}'] = g.transform(
            lambda s: s.shift(1).rolling(window).sum())
    panel['sin_month'] = np.sin(2 * np.pi * panel.month.dt.month / 12)
    panel['cos_month'] = np.cos(2 * np.pi * panel.month.dt.month / 12)
    panel['target'] = (panel['count'] > 0).astype(int)
    return panel.dropna().reset_index(drop=True), d


def metrics(y, probability, threshold):
    predicted = probability >= threshold
    return dict(n=len(y), prevalence=float(y.mean()),
                average_precision=float(average_precision_score(y, probability)),
                roc_auc=float(roc_auc_score(y, probability)),
                brier=float(brier_score_loss(y, probability)),
                precision=float(precision_score(y, predicted, zero_division=0)),
                recall=float(recall_score(y, predicted, zero_division=0)),
                f1=float(f1_score(y, predicted, zero_division=0)),
                confusion_matrix=confusion_matrix(y, predicted, labels=[0, 1]).tolist())


def run(source, output, end):
    output.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(source)
    panel, selected = build_panel(raw, pd.Period(end, 'M'))
    months = sorted(panel.month.unique())
    a, b = int(len(months) * .6), int(len(months) * .8)
    train = panel[panel.month < months[a]]
    valid = panel[(panel.month >= months[a]) & (panel.month < months[b])]
    test = panel[panel.month >= months[b]]
    for part in (train, valid, test):
        if part.target.nunique() != 2:
            raise ValueError('Each time split must contain both classes')
    numeric = ['lag1', 'lag12', 'past3', 'past6', 'sin_month', 'cos_month']
    transform = ColumnTransformer([
        ('numeric', StandardScaler(), numeric),
        ('country', OneHotEncoder(handle_unknown='ignore'), ['country'])])
    model = make_pipeline(transform, LogisticRegression(max_iter=2000, C=1.0))
    model.fit(train, train.target)
    vp = model.predict_proba(valid)[:, 1]
    thresholds = np.arange(.05, .96, .01)
    threshold = float(max(thresholds, key=lambda t: f1_score(valid.target, vp >= t)))
    tp = model.predict_proba(test)[:, 1]
    constant = np.full(len(test), train.target.mean())
    persistence = (test.lag1 > 0).astype(float).to_numpy()
    report = {
        'status': 'exploratory_snapshot_only', 'end_month': end,
        'selected_outbreaks': len(selected), 'countries': panel.country.nunique(),
        'excluded_countries_unseen_in_training': int(selected.country.nunique() - panel.country.nunique()),
        'threshold_selected_on_validation_f1': threshold,
        'splits': {name: {'start': str(p.month.min()), 'end': str(p.month.max()),
                           'rows': len(p)} for name, p in [('train', train), ('validation', valid), ('test', test)]},
        'validation': metrics(valid.target, vp, threshold),
        'test': metrics(test.target, tp, threshold),
        'baseline_constant': metrics(test.target, constant, .5),
        'baseline_previous_month': metrics(test.target, persistence, .5),
        'limitations': [
            'Absent records assumed zero; reporting/collection completeness unverified.',
            'Current snapshot lacks historical availability timestamps; reporting delay and revisions can leak future knowledge.',
            'Non-poultry HPAI category starts in 2017; historical surveillance/category comparability unverified.',
            'Country universe limited to countries observed in training; never-reported countries excluded.',
            'No causal interpretation, external climate/livestock predictors, or production deployment.',
            'Temporal holdout does not substitute for rolling backtests or external validation.']}
    (output / 'metrics.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    predictions = test[['country', 'month', 'count', 'target']].copy()
    predictions['probability'] = tp
    predictions['predicted'] = (tp >= threshold).astype(int)
    predictions.to_csv(output / 'test_predictions.csv', index=False)
    names = model[0].get_feature_names_out()
    coefficients = pd.DataFrame({'feature': names, 'coefficient': model[-1].coef_[0]})
    coefficients['odds_ratio'] = np.exp(coefficients.coefficient)
    coefficients.to_csv(output / 'coefficients.csv', index=False)
    panel.to_csv(output / 'monthly_panel.csv', index=False)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('wahis_outbreaks_all.csv'))
    parser.add_argument('--output', type=Path, default=Path('data/modeling/hpai_logistic'))
    parser.add_argument('--end-month', required=True, help='Conservative closed month, YYYY-MM')
    args = parser.parse_args()
    run(args.source, args.output, args.end_month)
