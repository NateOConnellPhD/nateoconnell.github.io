"""Additive export against the real scorer, with synthetic draws; no HMC/API."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from game_contributions import build, validate, exact_reader
from loo_scoring import aggregate_credits, flatten, score
from reference_config import REFERENCE_RANKS
from sync_data import digest


def fixture(rank=12):
    rng = np.random.default_rng(61)
    flat = dict(theta=rng.normal(0, 10, (40, 26)), home_adv=np.full(40, 3.),
                sigma=np.full(40, 14.), nu=np.full(40, 8.), home_effect=np.tile([3., 2., -1.], (40, 1)))
    data = dict(home=[0, 1, 0, 24], away=[1, 24, 2, 25], venue=[0, 1, 1, 0],
                host=[0, 2, 1, 0], margin=[7, -3, 21, 14])
    games = [dict(id=100+i, week=i, start_date=f'2026-09-{i+1:02d}T18:00:00Z',
                  home_id=h, away_id=a, home_points=max(m, 0)+7, away_points=max(-m, 0)+7,
                  neutral_site=not data['venue'][i])
             for i, (h, a, m) in enumerate(zip(data['home'], data['away'], data['margin']))]
    inputs = dict(data=data, games=games, fbs_indices=list(range(24)), scored_game_indices=[0, 1, 2])
    weights = np.tile(np.arange(1, 41)/820, (4, 1))
    exact = {0: {k: np.linspace(.02, .92, 7)**2 for k in ('home_cdf', 'away_cdf', 'home_sos', 'away_sos')}}
    scored = aggregate_credits(flat, data, weights, rank, exact=exact, reference_indices=inputs['fbs_indices'], scored_indices=[0, 1, 2])
    report = dict(identity=dict(reference_rank=rank), diagnostics=dict(relative_efficiency=1., threshold=.7),
                  game_audit=[dict(row, game_id=games[row['game']]['id'], method='exact_loo' if row['game'] == 0 else 'psis_loo') for row in scored['audit']])
    teams = []
    for i in range(24):
        wins = sum((g['home_id'] == i and g['home_points'] > g['away_points']) or (g['away_id'] == i and g['away_points'] > g['home_points']) for g in games)
        played = sum(i in (g['home_id'], g['away_id']) for g in games)
        teams.append(dict(id=i, wins=wins, losses=played-wins, merit_mean=float(scored['merit'][:, i].mean())))
    result = dict(reference_rank=rank, teams=teams, policy_inputs=dict(games=games[:3]))
    return flat, inputs, weights, exact, report, result


class GameContributionTests(unittest.TestCase):
    def test_all_references_reconcile_with_transport_and_exact_fcs_home_and_away(self):
        for rank in REFERENCE_RANKS:
            flat, inputs, weights, exact, report, result = fixture(rank)
            with patch('loo_scoring.loo_weights', return_value=(weights[:1], np.array([.1]))):
                block = build(flat, inputs, report, lambda i, game_id: exact[i])
            result['game_contributions'] = block
            validate(result)
            self.assertEqual([g['id'] for g in block['games']], [100, 101, 102], 'No FCS-only game becomes earned merit')
            self.assertEqual(block['games'][1]['away_id'], 24, 'FBS–FCS contributions are included')
            self.assertLess(block['games'][1]['home_credit']['mean'], 0, 'Home loss has negative credit')
            self.assertGreater(block['games'][1]['away_credit']['mean'], 0, 'Away win has positive credit')
            self.assertTrue(block['games'][0]['neutral_site'])
            # This deliberately exposes the old weighted-vs-transported gap.
            self.assertNotAlmostEqual(block['games'][0]['home_credit']['mean'], report['game_audit'][0]['home_credit'], places=5)
            single = aggregate_credits(flat, inputs['data'], weights, rank, exact=exact,
                                       reference_indices=inputs['fbs_indices'], scored_indices=[0])
            self.assertAlmostEqual(block['games'][0]['home_credit']['median'], np.median(single['merit'][:, 0]))

    def test_reconstructed_psis_matches_actual_score_without_mocked_weights(self):
        rng = np.random.default_rng(47)
        samples = dict(theta=rng.normal(0, 1, (4, 100, 24)), home_adv=np.full((4, 100), 3.),
                       sigma=np.full((4, 100), 14.), nu=np.full((4, 100), 8.))
        _, inputs, _, _, _, _ = fixture()
        inputs['data'] = dict(home=[0], away=[1], venue=[0], margin=[7])
        inputs['games'] = inputs['games'][:1]; inputs['scored_game_indices'] = [0]
        saved = score(samples, inputs['data'], reff=1., reference_indices=list(range(24)))
        report = dict(identity=dict(reference_rank=12), diagnostics=saved['diagnostics'],
                      game_audit=[dict(saved['audit'][0], game_id=100)])
        block = build(flatten(samples), inputs, report, lambda *args: self.fail('No exact refit should be requested'))
        for side, i in [('home', 0), ('away', 1)]:
            self.assertAlmostEqual(block['games'][0][side+'_credit']['mean'], saved['merit'][:, i].mean(), places=12)

    def test_publication_rejects_wrong_reference_missing_duplicate_or_corrupt_credit(self):
        flat, inputs, weights, exact, report, result = fixture()
        with patch('loo_scoring.loo_weights', return_value=(weights[:1], np.array([.1]))):
            result['game_contributions'] = build(flat, inputs, report, lambda i, game_id: exact[i])
        variants = []
        bad = copy.deepcopy(result); bad['game_contributions']['reference_rank'] = 2; variants.append(bad)
        bad = copy.deepcopy(result); bad['game_contributions']['games'].pop(); variants.append(bad)
        bad = copy.deepcopy(result); bad['game_contributions']['games'][1] = bad['game_contributions']['games'][0]; variants.append(bad)
        bad = copy.deepcopy(result); bad['game_contributions']['games'][0]['home_credit']['mean'] += .001; variants.append(bad)
        bad = copy.deepcopy(result); bad['game_contributions']['games'][0]['home_points'] += 1; variants.append(bad)
        for bad in variants:
            with self.assertRaises(ValueError): validate(bad)
        report['game_audit'][1]['home_credit'] += .001
        with patch('loo_scoring.loo_weights', return_value=(weights[:1], np.array([.1]))):
            with self.assertRaisesRegex(ValueError, 'checked game audit'): build(flat, inputs, report, lambda i, game_id: exact[i])

    def test_exact_reader_reuses_existing_identity_and_checks_arrays(self):
        source = dict(fit_key='fit', exact_runner_source='runner', exact_sampling_source='sampling',
                      reference_source='reference', scorer_source='scorer', reference_rank=4)
        identity = dict(fit_key='fit', game_id=100, runner_source='runner', sampling_source='sampling',
                        reference_source='reference', reference_ranks=list(REFERENCE_RANKS), scorer_source='scorer', seed=107)
        with tempfile.TemporaryDirectory(dir=os.environ['CFB_TEST_TMP']) as folder:
            task = Path(folder); cache = task/'exact'/digest(identity); cache.mkdir(parents=True)
            path = cache/'quantities.npz'
            arrays = {f'r{r}_{k}': np.full(8, r/25) for r in REFERENCE_RANKS for k in ('home_cdf', 'away_cdf', 'home_sos', 'away_sos')}
            np.savez_compressed(path, **arrays)
            (cache/'report.json').write_text(json.dumps(dict(identity=identity, diagnostics=dict(sampling_checks_passed=True), array_sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
            read = exact_reader(task, dict(identity=source), dict(identity=dict(seed=7)))
            np.testing.assert_array_equal(read(0, 100)['home_cdf'], np.full(8, .16))
            path.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'integrity'): read(0, 100)


if __name__ == '__main__':
    unittest.main()
