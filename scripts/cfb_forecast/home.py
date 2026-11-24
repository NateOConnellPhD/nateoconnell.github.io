"""Map saved history to the supplied home-field estimator, without changing it."""
import json
from pathlib import Path
from sync_data import digest, encoded


def load_or_estimate(inputs, cache):
    import numpy as np
    import pandas as pd
    from .reference.historical_home import robust_history_fit, current_home_prior
    history = inputs['home_history']
    ids = [inputs['teams'][i]['id'] for i in inputs['fbs_indices']]
    identity = {'history': history['input_sha256'], 'fbs_ids': ids,
        'adapter': digest(Path(__file__).read_text()),
        'supplied_estimator': digest((Path(__file__).parent/'reference/historical_home.py').read_text())}
    path = Path(cache)/(digest(identity)+'.json')
    if path.exists():
        saved=json.loads(path.read_text())
        if saved['identity']!=identity or saved['prior_sha256']!=digest(saved['prior']):
            raise ValueError('Forecast home-prior cache integrity failure')
        return saved['prior']
    # String IDs are opaque team names to the original estimator. They avoid
    # spelling aliases while preserving season-specific team strengths.
    games=pd.DataFrame([{'season':g['season'],'home_team':str(g['home_id']),
        'away_team':str(g['away_id']),'neutral_site':not bool(g['venue']),
        'margin':g['margin']} for g in history['games']])
    fit=robust_history_fit(games)
    original=current_home_prior(fit, set(games.home_team)|set(games.away_team), set(map(str,ids)))
    order=[original['names'].index('__national__')]+[original['names'].index(str(i)) for i in ids]
    mean=original['mean'][order]; covariance=original['covariance'][np.ix_(order,order)]
    prior={'fbs_ids':ids,'years':history['years'],'mean':mean.tolist(),
        'covariance':covariance.tolist(),'chol':np.linalg.cholesky(covariance).tolist(),
        'history_input_sha256':history['input_sha256'],
        'diagnostics':{'games':len(games),'iterations':fit['fit_iterations'],
            'approximation':'Supplied robust Student-t home estimator with IRLS covariance'}}
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(encoded({'identity':identity,'prior':prior,'prior_sha256':digest(prior)}))
    return prior
