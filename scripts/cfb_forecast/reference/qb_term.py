"""QB term for the production run: QB values (code/qb_model.py) -> covariate x for training games (who played) and for
upcoming games (who is expected to start), plus each team's QB importance.

  x_{team, game} = nbar_team * (v_QB - v_ref_team)
  v_ref: dropback-weighted value of the team's passers so far this season (the team rating is strength with its usual mix)
  nbar : team's non-garbage dropbacks per game so far, shrunk toward 27 with 3 pseudo-games
The margin model adds lambda * (x_home - x_away), lambda learned (prior N(1, 0.5^2)).
Expected starter: the passer who took the team's first dropback in its most recent game, unless overridden in
data/qb/qb_status_<season>.csv (team, passer_id or name, note)."""
import json
from pathlib import Path
import numpy as np, pandas as pd
from qb_model import prepare, solve, career_before


class QBTerm:
    def __init__(self, data, season, through_week, hyper_path):
        data = Path(data)
        db = pd.concat([pd.read_parquet(f) for f in sorted((data / 'pbp').glob('dropbacks_*.parquet'))])
        self.db = db[db.n > 0]
        fbs = {}
        for f in sorted((data / 'cfbd').glob('cfb_schedules_*.csv')):
            y = int(f.stem[-4:]); s = pd.read_csv(f, low_memory=False)
            fbs[y] = set(s.loc[s.home_division == 'fbs', 'home_team']) | set(s.loc[s.away_division == 'fbs', 'away_team'])
        self.season, self.week = season, through_week + 1
        self.cb = career_before(self.db); self.cbl = dict(zip(zip(self.cb.passer_id, self.cb.season), self.cb.career_before))
        self.hp = json.loads(Path(hyper_path).read_text())
        d = prepare(self.db, fbs, cutoff=(season, self.week), cb=self.cb)
        self.r = solve(d, self.hp)
        self.S = self.db[(self.db.season == season) & (self.db.season_type == 'regular') & (self.db.week < self.week)].sort_values(['week', 'game_id'])
        names = []
        for f in sorted((data / 'pbp').glob('qb_names_*.csv')):
            names.append(pd.read_csv(f))
        self.names = pd.concat(names).drop_duplicates('passer_id', keep='last').set_index('passer_id').name if names else pd.Series(dtype=str)

    def value(self, pid, before_week=None):
        before_week = self.week if before_week is None else before_week
        n_before = self.cbl.get((pid, self.season), 0.) + self.S[(self.S.passer_id == pid) & (self.S.week < before_week)].n.sum()
        return self.r['value'](pid, self.season, float(np.log1p(self.cbl.get((pid, self.season), 0.) / 100.)), float(n_before < 50))

    def _team_state(self, team, before_week):
        prev = self.S[(self.S.pos_team == team) & (self.S.week < before_week)]
        if prev.empty:
            return None
        pw = prev.groupby('passer_id').n.sum()
        v_ref = float(np.average([self.value(p, before_week) for p in pw.index], weights=pw.values))
        nbar = (prev.n.sum() + 27. * 3) / (prev.game_id.nunique() + 3)
        last = prev[prev.week == prev.week.max()]
        incumbent = last.sort_values('first_play').passer_id.iloc[0]
        return {'v_ref': v_ref, 'nbar': nbar, 'incumbent': incumbent, 'mix': pw}

    def x_training(self, games, mode='start'):
        """games: rows with game_id, week, home_team, away_team -> home minus away x.
        mode 'start': the passer who took the first dropback (known at kickoff; the production setting, variant S);
        mode 'played': dropback-weighted mix of who played (variant Q; in-game changes make lambda too large)."""
        out = []
        for g in games.itertuples():
            xs = []
            for team in (g.home_team, g.away_team):
                st = self._team_state(team, g.week)
                mix = self.S[(self.S.game_id == g.game_id) & (self.S.pos_team == team)]
                if st is None or mix.empty:
                    xs.append(0.); continue
                if mode == 'start':
                    v_played = self.value(mix.sort_values('first_play').passer_id.iloc[0], g.week)
                else:
                    v_played = float(np.average([self.value(p, g.week) for p in mix.passer_id], weights=mix.n))
                xs.append(st['nbar'] * (v_played - st['v_ref']))
            out.append(xs[0] - xs[1])
        return np.array(out)

    def x_for(self, team, passer_id=None):
        """x for an upcoming game if passer_id starts (default: the incumbent)."""
        st = self._team_state(team, self.week)
        if st is None:
            return 0., None
        pid = st['incumbent'] if passer_id is None else passer_id
        return st['nbar'] * (self.value(pid) - st['v_ref']), pid

    def importance(self, teams, lam):
        """Points the team loses if its incumbent is replaced by the next passer: the non-incumbent with the most dropbacks
        among those who played in the team's last four games (else this season; else a first-time passer at replacement)."""
        rows = []
        for t in teams:
            st = self._team_state(t, self.week)
            if st is None: continue
            inc = st['incumbent']; others = st['mix'].drop(inc, errors='ignore').sort_values(ascending=False)
            prev = self.S[self.S.pos_team == t]; recent_weeks = sorted(prev.week.unique())[-4:]
            recent = set(prev[prev.week.isin(recent_weeks)].passer_id)            # a backup who has played lately is likelier active
            cand = [p for p in others.index if p in recent] or list(others.index)
            backup = cand[0] if cand else None
            v_inc = self.value(inc)
            v_bk = self.value(backup) if backup is not None else self.r['f_r']          # replacement: no experience, first-timer
            rows.append({'team': t, 'qb': self.names.get(inc, str(inc)), 'passer_id': inc, 'qb_value': v_inc,
                         'backup': self.names.get(backup, str(backup)) if backup is not None else 'replacement level',
                         'backup_id': backup, 'backup_value': v_bk, 'dropbacks_per_game': st['nbar'],
                         'importance_pts': lam * st['nbar'] * (v_inc - v_bk)})
        return pd.DataFrame(rows)
