"""Extend the supplied annual evidence with the supplied estimators, once/year."""
import copy
import datetime as dt
import importlib
import sys

from .refresh import DIRECTORY, ROOT, read, write, prior_builder_key
from sync_data import DATA, digest, instant, merge_games, normalize


def reference_priors():
    # The unchanged handoff uses sibling absolute imports. Bind only those two
    # names while importing it, then restore the host application's namespace.
    aliases = {name:importlib.import_module('.reference.'+name, 'cfb_forecast')
               for name in ('forecast_model','historical_home')}
    old = {name:sys.modules.get(name) for name in aliases}
    try:
        sys.modules.update(aliases)
        return importlib.import_module('.reference.priors_v7', 'cfb_forecast')
    finally:
        for name, value in old.items():
            if value is None: sys.modules.pop(name, None)
            else: sys.modules[name] = value


def season_frame(year, data=DATA):
    import pandas as pd
    folder = data/str(year)
    sources = {n:read(folder/(n+'.json')) for n in ('teams','games','games-fcs')}
    if any(v is None for v in sources.values()): raise ValueError(f'Missing completed {year} feeds for annual forecasting prior')
    observed = min(instant(s['retrieved_at']) for n,s in sources.items() if n != 'teams')
    if observed < dt.datetime(year+1,7,1,tzinfo=dt.timezone.utc): raise ValueError(f'{year} feed has not been refreshed after the season')
    raw = merge_games(sources['games']['payload'], sources['games-fcs']['payload'])
    normalized = normalize(year, sources['teams']['payload'], None, raw, observed, include_fcs=True, require_calendar=False)
    # Original annual Gaussian/ridge estimators use ALL completed DI games,
    # including bowls and FCS playoffs. Current-season forecasting remains regular-season only.
    rows = [g for g in normalized['games'] if not set(g['exclusions']) - {'fcs_playoff','postseason_not_in_scope'}]
    if len(rows) < 500 or any(g['home_points'] == g['away_points'] for g in rows):
        raise ValueError(f'Incomplete or tied annual DI game evidence for {year}')
    frame = pd.DataFrame([{'season':year,'game_id':g['id'],'week':g['week'],'season_type':g['season_type'],
        'home_team':str(g['home_id']),'away_team':str(g['away_id']),
        'home_division':'fbs' if g['home_fbs'] else 'fcs','away_division':'fbs' if g['away_fbs'] else 'fcs',
        'home_points':g['home_points'],'away_points':g['away_points'],'neutral_site':g['neutral_site'], 'completed':True}
        for g in rows])
    return frame, {n:s['payload_sha256'] for n,s in sources.items()}


def annual_summary(year, data=DATA):
    from .reference.forecast_model import season_ratings
    frame, hashes = season_frame(year, data)
    fbs = set(frame.loc[frame.home_division.eq('fbs'),'home_team']) | set(frame.loc[frame.away_division.eq('fbs'),'away_team'])
    rating = season_ratings(frame[frame.home_division.eq('fbs') | frame.away_division.eq('fbs')], fbs)
    original = reference_priors()
    class SavedData:
        @staticmethod
        def sched(y):
            if y != year: raise ValueError('Unexpected annual year')
            return frame
        di = staticmethod(original.Data.di)
    ridge = original.di_ratings(SavedData(), year)
    numeric = {k:float(rating[k]) for k in ('mu_fcs','tau_fbs','tau_fcs','sigma')}
    numeric.update(fbs=sorted(fbs), **{k:{t:float(rating[k][t]) for t in fbs} for k in ('mean','var')})
    early = [{'season':year,'week':int(g.week),'season_type':'regular','home':g.home_team,'away':g.away_team,
        'neutral':bool(g.neutral_site),'margin':float(g.home_points-g.away_points)} for g in frame.itertuples()
        if g.season_type == 'regular' and g.week <= 5 and g.home_division == g.away_division == 'fbs']
    return {'season':year,'ratings':numeric,'fcs_ratings':{k:float(v) for k,v in ridge.items()},
            'early_games':early,'source_hashes':hashes}


def build_live(season, directory=DIRECTORY, data=DATA, prior_directory=None, summarizer=annual_summary):
    from .priors import build
    prior_directory = prior_directory or ROOT/'_cfb_data/forecast_priors'
    bundle = read(directory/'evidence.json')
    # Supplied historical summaries remain immutable. Future seasons freeze
    # their last observed covariates when they enter the annual training set.
    for year in range(2026, season):
        path = directory/'annual'/f'{year}.json'
        saved = read(path)
        if saved is None or saved.get('builder_key') != prior_builder_key():
            live = read(directory/'live'/f'{year}.json')
            if live is None: raise ValueError(f'Missing saved {year} covariates; no substituted annual prior')
            saved = {**summarizer(year, data), 'covariates':saved['covariates'] if saved else live['covariates'],
                'roster':saved['roster'] if saved else live['roster'], 'builder_key':prior_builder_key()}
            write(path, saved)
        y = str(year)
        for key in ('ratings','fcs_ratings','covariates'): bundle[key][y] = saved[key]
        bundle['rosters'][y] = saved['roster']
        bundle['early_games'] = [g for g in bundle['early_games'] if g['season'] != year] + saved['early_games']
        bundle['source_hashes']['annual/'+y] = digest(saved)
    live = read(directory/'live'/f'{season}.json')
    if live is None: raise ValueError('Current covariates have not been collected')
    y = str(season); bundle['rosters'][y] = live['roster']; bundle['covariates'][y] = live['covariates']
    bundle['caveats'][y] = 'Current covariates refresh daily. This snapshot preserves the values used; reconstructed historical windows may use later observations.'
    key = digest({'roster':live['roster'],'covariates':live['covariates']})
    bundle['source_hashes']['live/'+y] = key
    prior = build(bundle, season)
    prior['live_input_key'] = key
    prior['builder_key'] = prior_builder_key()
    # Keep observation dates of the values used, without turning repeated
    # successful checks of unchanged values into a new numerical fit.
    prior['input_observations'] = copy.deepcopy(live['sources'])
    path = prior_directory/'live'/f'{season}.json'
    old = read(path)
    if old and {k:v for k,v in old.items() if k != 'input_observations'} == {k:v for k,v in prior.items() if k != 'input_observations'}:
        return old
    write(path, prior)
    if not (prior_directory/f'{season}.json').exists(): write(prior_directory/f'{season}.json', prior)
    return prior
