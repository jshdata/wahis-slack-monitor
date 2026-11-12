"""Post-2017 exploratory expanding-window comparison (snapshot availability caveat)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from modeling.hpai_logistic import build_panel, metrics


def features(panel):
    p = panel.copy()
    for name in ['lag1', 'lag12', 'past3', 'past6']:
        p['log_' + name] = np.log1p(p[name])
    p['previous_positive'] = (p.lag1 > 0).astype(int)
    p['previous_year_positive'] = (p.lag12 > 0).astype(int)
    return p


def fit_model(train, columns, c):
    transform = ColumnTransformer([
        ('numeric', StandardScaler(), columns),
        ('country', OneHotEncoder(handle_unknown='ignore'), ['country'])])
    model = make_pipeline(transform, LogisticRegression(C=c, max_iter=2000))
    model.fit(train, train.target)
    return model


def evaluate(panel):
    # Cohort determined once using only pre-2020 history.
    countries = panel.loc[(panel.month < pd.Period('2020-01')) &
                          (panel['count'] > 0), 'country'].unique()
    panel = panel[panel.country.isin(countries)].copy()
    columns = ['log_lag1', 'log_lag12', 'log_past3', 'log_past6',
               'previous_positive', 'previous_year_positive', 'sin_month', 'cos_month']
    predictions, folds = [], []
    for year in range(2021, 2027):
        start = pd.Period(f'{year}-01')
        valid_start = start - 12
        train = panel[panel.month < valid_start]
        valid = panel[(panel.month >= valid_start) & (panel.month < start)]
        test = panel[(panel.month >= start) & (panel.month < start + 12)]
        if test.empty:
            continue
        best = None
        for c in [.1, 1., 10.]:
            model = fit_model(train, columns, c)
            probability = model.predict_proba(valid)[:, 1]
            for threshold in np.arange(.1, .81, .05):
                score = f1_score(valid.target, probability >= threshold)
                if best is None or score > best[0]:
                    best = (score, c, float(threshold))
        # Hyperparameters/threshold frozen before the test window.
        history = panel[panel.month < start]
        model = fit_model(history, columns, best[1])
        probability = model.predict_proba(test)[:, 1]
        out = test[['country', 'month', 'target']].copy()
        out['probability'] = probability
        out['prediction'] = (probability >= best[2]).astype(int)
        out['persistence'] = (test.lag1 > 0).astype(int)
        out['threshold'] = best[2]
        predictions.append(out)
        folds.append({'year': year, 'train_end': str(history.month.max()),
                      'validation_start': str(valid.month.min()),
                      'validation_end': str(valid.month.max()),
                      'test_start': str(test.month.min()), 'test_end': str(test.month.max()),
                      'C': best[1], 'threshold': best[2],
                      'logistic': metrics(test.target, probability, best[2]),
                      'persistence': metrics(test.target, out.persistence.to_numpy(), .5)})
    all_predictions = pd.concat(predictions, ignore_index=True)
    overall = metrics(all_predictions.target, all_predictions.probability.to_numpy(), .5)
    # Thresholds differ between folds, so classification uses each fold's frozen value.
    from sklearn.metrics import precision_score, recall_score, confusion_matrix
    y, pred = all_predictions.target, all_predictions.prediction
    overall.update(precision=float(precision_score(y, pred)),
                   recall=float(recall_score(y, pred)), f1=float(f1_score(y, pred)),
                   confusion_matrix=confusion_matrix(y, pred, labels=[0, 1]).tolist())
    return {'status': 'exploratory_snapshot_reanalysis_not_unseen_confirmation',
            'countries': len(countries), 'logistic': overall,
            'persistence': metrics(y, all_predictions.persistence.to_numpy(), .5),
            'folds': folds}, all_predictions


def run():
    raw = pd.read_csv('wahis_outbreaks_all.csv')
    raw = raw[pd.to_datetime(raw.start_date) >= '2017-01-01']
    panel, _ = build_panel(raw, pd.Period('2026-06'))
    report, predictions = evaluate(features(panel))
    output = Path('data/modeling/hpai_rolling')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'metrics.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    predictions.to_csv(output / 'predictions.csv', index=False)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    run()
