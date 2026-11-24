"""Dataframe boundary for the handoff's pipeline/pbp_dropbacks.py.

Same passer repair, garbage-time thresholds, grouping and name selection.
Missing season labels are recovered from the schedule by game ID before grouping.
"""
def dropbacks(df, season, season_types=None):
    import numpy as np
    import pandas as pd
    required = {'pass', 'EPA', 'completion_player_id', 'incompletion_player_id',
        'interception_thrown_player_id', 'sack_taken_player_id', 'pos_team', 'def_pos_team',
        'game_id', 'home', 'away', 'week', 'season_type', 'pos_score_diff_start', 'period', 'game_play_number'}
    if not required <= set(df.columns):
        raise ValueError('Play-by-play schema changed: ' + ', '.join(sorted(required - set(df.columns))))
    p = df[(df['pass'].astype(float) == 1) & df.EPA.notna()].copy()
    # The live feed can omit this label even when its game and EPA are complete.
    # Recover metadata from the schedule, never infer regular/postseason from a
    # week number. Do this before grouping so one passer-game stays one row.
    if season_types:
        p['season_type'] = p.season_type.astype(object)
        missing = p.season_type.isna() | p.season_type.isin(['', 'NA'])
        p.loc[missing, 'season_type'] = pd.to_numeric(
            p.loc[missing, 'game_id'], errors='coerce').map(season_types)
    pid = pd.to_numeric(p.completion_player_id, errors='coerce')
    other = pd.to_numeric(p.incompletion_player_id, errors='coerce')
    for c in ('interception_thrown_player_id', 'sack_taken_player_id'):
        other = other.fillna(pd.to_numeric(p[c], errors='coerce'))
    p['passer_id'] = pid.fillna(other)
    has = other.notna(); legit = set(zip(p.loc[has, 'pos_team'], other[has]))
    ok = pd.Series([(t, i) in legit for t, i in zip(p.pos_team, p.passer_id)], index=p.index)
    main = p[ok].groupby(['game_id', 'pos_team']).passer_id.agg(lambda x: x.value_counts().index[0])
    fix = ~ok & p.passer_id.notna()
    p.loc[fix, 'passer_id'] = [main.get((g, t), np.nan) for g, t in zip(p.loc[fix, 'game_id'], p.loc[fix, 'pos_team'])]
    lead = pd.to_numeric(p.pos_score_diff_start, errors='coerce').abs(); q = p.period.astype(float)
    p = p[~(((q == 2) & (lead > 38)) | ((q == 3) & (lead > 28)) | ((q == 4) & (lead > 22)))]
    p = p[p.passer_id.notna()].copy()
    p['EPA'] = p.EPA.astype(float); p['epa2'] = p.EPA ** 2; p['season'] = season
    keys = ['season', 'week', 'season_type', 'game_id', 'home', 'away', 'pos_team', 'def_pos_team', 'passer_id']
    g = p.groupby(keys, dropna=False).agg(n=('EPA', 'size'), epa_sum=('EPA', 'sum'),
        epa2_sum=('epa2', 'sum'), first_play=('game_play_number', 'min')).reset_index()
    g['passer_id'] = g.passer_id.astype('int64'); g['game_id'] = g.game_id.astype('int64')
    names = {}
    if 'passer_player_name' in p:
        nm = p[p.passer_player_name.notna()].groupby('passer_id').passer_player_name.agg(lambda x: x.value_counts().index[0])
        names = {str(int(k)): str(v) for k,v in nm.items()}
    return g, names
