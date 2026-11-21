"""Offline archive-boundary checks; no API requests or numerical dependencies."""
import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cache_identity as identities
import historical_rankings as history
import update_rankings as pipeline
from ranking_policy import order_policy, prepare_policy
from sync_data import ROOT, UTC, encoded, envelope
from sync_polls import sync_polls
from test_polls import TEAMS, polls
from policy_fixtures import games, probability, teams


class ArchiveRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = ROOT / '.codex-tmp' / 'cfb-archive-review'
        cls.base.mkdir(parents=True, exist_ok=False)

    @classmethod
    def tearDownClass(cls):
        cls.base.rmdir()

    def test_same_rules_allow_one_loss_above_undefeated_in_every_season(self):
        roster = teams(3)
        roster[0]['conference'] = 'ACC'
        states = []
        for season in range(2002, 2027):
            # A: 8–0; B: 8–1; C: 1–16. B has the higher estimated merit.
            results = games([(1, 3)] * 8 + [(2, 3)] * 8 + [(3, 2)])
            for game in results:
                game['season'] = season
            state = prepare_policy(roster, results, [2, 3, 0], probability(3, {(2, 1): .99}), season=season)
            result = order_policy(state)
            self.assertEqual(result['order'], [2, 1, 3])
            self.assertEqual(result['protected_team_ids'], [1])
            self.assertFalse(any(a['type'] == 'undefeated_p4' and a['loser_id'] == 2 for a in result['audit']))
            states.append(state)
        with self.assertRaisesRegex(ValueError, '2002'):
            prepare_policy(roster, [], [2, 3, 0], probability(3), season=2001)

    def test_cache_bridge_requires_the_exact_reviewed_source_bundle(self):
        current, previous = identities.source_identities()
        self.assertEqual(identities.publication_sources(2002), current)
        self.assertEqual(identities.publication_sources(2026), previous or current)
        self.assertEqual(identities.runner_identity(), (previous or current)['fit_saved_season.py'])
        original = Path.read_bytes
        def changed(path):
            return original(path) + (b'\n# changed model\n' if path.name == 'model.py' else b'')
        with patch.object(Path, 'read_bytes', changed):
            changed_sources, fallback = identities.source_identities()
            self.assertIsNone(fallback)
            self.assertNotEqual(changed_sources, current)
            self.assertEqual(identities.publication_sources(2026), changed_sources)

    def test_queue_imports_one_season_and_keeps_older_seasons_pending(self):
        with tempfile.TemporaryDirectory(dir=self.base) as temporary:
            root = Path(temporary)
            data, task, public = root / 'data', root / 'task', root / 'public'
            fetched, written = [], []
            def save_season(season, key=None):
                folder = data / str(season)
                folder.mkdir(parents=True)
                calendar = [{'week': week, 'seasonType': 'regular', 'endDate': f'{season}-09-{7*week:02d}T12:00:00Z'} for week in (1, 2)]
                for name, payload in (('teams', []), ('calendar', calendar), ('games', []), ('games-fcs', [])):
                    (folder / f'{name}.json').write_bytes(encoded({'payload': payload, 'retrieved_at': '2026-11-20T12:00:00Z'}))
                fetched.append(season)
            for season in (2024, 2025, 2026):
                save_season(season)
            fetched.clear()
            output = root / 'outputs'
            def matching(index, key, *args, **kw):
                return {'id': 'saved'} if int(key.split('-')[0]) >= 2024 else None
            with patch.object(history, 'DATA', data), patch.object(history, 'sync', side_effect=save_season), \
                 patch.object(history, 'load_inputs', side_effect=lambda season, through_week: {'season': season, 'through_week': through_week}), \
                 patch.object(pipeline, 'current_season', return_value=2026), \
                 patch.object(pipeline, 'PUBLIC', public), patch.object(pipeline, 'TASK', task), \
                 patch.object(pipeline, 'PLAN', task / 'plan.json'), \
                 patch.object(pipeline, 'read_index', return_value={'snapshots': []}), \
                 patch.object(pipeline, 'write_index', side_effect=lambda index: written.append(index)), \
                 patch.object(pipeline, 'request_key', side_effect=lambda inputs: f"{inputs['season']}-{inputs['through_week']}"), \
                 patch.object(pipeline, 'matching_snapshot', side_effect=matching) as match, \
                 patch.dict(os.environ, {'GITHUB_OUTPUT': str(output)}), contextlib.redirect_stdout(io.StringIO()):
                history.prepare_history()
                self.assertEqual(fetched, [2023])
                plan = json.loads((task / 'plan.json').read_text())
                self.assertEqual((plan['season'], plan['through_week']), (2023, 2))
                self.assertEqual(written[-1]['backfill']['pending_seasons'], list(range(2022, 2001, -1)))
                self.assertEqual(written[-1]['backfill']['remaining'], 2)
                self.assertEqual(written[-1]['backfill']['status'], 'pending')
                self.assertIn('continue_history=true', output.read_text())
                # Simulate completion of 2023; the next run advances to 2022,
                # preserving all previously imported input files.
                match.side_effect = lambda index, key, *a, **kw: {'id': 'saved'} if int(key.split('-')[0]) >= 2023 else None
                history.prepare_history()
                self.assertEqual(fetched, [2023, 2022])
                self.assertEqual(json.loads((task / 'plan.json').read_text())['season'], 2022)
                # A season with no eligible games must not stop discovery of
                # the remaining years or try to fit a nonexistent cutoff.
                with patch.object(history, 'load_inputs', side_effect=ValueError('No eligible completed games at the selected cutoff')):
                    history.prepare_history()
                    plan = json.loads((task / 'plan.json').read_text())
                    self.assertTrue(plan['history_scan_only'])
                    self.assertFalse(plan['history_done'])
                    self.assertFalse(plan['needs_fit'])
                for season in range(2020, 2001, -1):
                    save_season(season)
                match.side_effect = lambda *a, **kw: {'id': 'saved'}
                history.prepare_history()
                self.assertTrue(json.loads((task / 'plan.json').read_text())['history_done'])
                self.assertEqual(written[-1]['backfill']['status'], 'complete')
                self.assertEqual(written[-1]['backfill']['pending_seasons'], [])
                self.assertEqual(written[-1]['archive'][-1]['season'], 2002)

    def test_2002_poll_import_and_closed_season_reuse(self):
        with tempfile.TemporaryDirectory(dir=self.base) as temporary:
            root = Path(temporary)
            data, public = root / 'data', root / 'public'
            folder = data / '2002'
            folder.mkdir(parents=True)
            now = dt.datetime(2026, 11, 20, tzinfo=UTC)
            (folder / 'teams.json').write_bytes(encoded(envelope(2002, '/teams/fbs', {'year': 2002}, TEAMS, now.isoformat())))
            calls = []
            def fetcher(path, params, key):
                calls.append((path, params))
                payload = polls(2002)
                payload[0]['polls'] = payload[0]['polls'][:1]  # AP only; do not invent an old CFP edition.
                return payload
            for expected in (1, 0):
                result = sync_polls(2002, 'fixture-key', destination=data, public=public, now=now, fetcher=fetcher)
                self.assertEqual(result['requests'], expected)
            self.assertEqual(calls, [('/rankings', {'year': 2002, 'seasonType': 'both'})])
            saved = json.loads((public / '2002/polls.json').read_text())
            self.assertEqual([p['poll'] for p in saved['editions']], ['ap'])


if __name__ == '__main__':
    unittest.main()
