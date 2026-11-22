"""Small offline cache-retention and guard checks; no downloads or model fits."""
import contextlib
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import prune_task_cache as cache
import run_bounded as bounded
from sync_data import ROOT, digest


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(os.environ.get('CFB_TEST_TMP', ROOT / '.codex-tmp' / 'cfb-storage-review'))
        self.created = not self.base.exists()
        self.base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.root = Path(self.temp.name)
        self.inputs = {'teams': [{'id': 1}, {'id': 2}], 'fbs_indices': [0],
                       'data': {'margin': [7]}, 'strength_structure': {'fixture': True},
                       'home_history': {'input_sha256': 'three-prior-seasons'}}

    def tearDown(self):
        self.temp.cleanup()
        if self.created:
            self.base.rmdir()

    def record(self, leaf, identity, filename, passed=True):
        folder = self.root / leaf / digest(identity)
        folder.mkdir(parents=True)
        (folder / filename).write_bytes(b'array fixture')
        (folder / 'report.json').write_text(json.dumps({'identity': identity,
            'diagnostics': {'sampling_checks_passed': passed}}))
        return folder

    def fitted(self, margin=7):
        ident = {'refit_generation': cache.REFIT_GENERATION,
                 'model_source': cache.source_hash('model.py'),
                 'diagnostic_source': cache.source_hash('refit_2024.py'),
                 'model_data_sha256': digest({'team_ids': [1, 2], 'data': {'margin': [margin]},
                                             'strength_structure': self.inputs['strength_structure']}),
                 'home_prior': {'history_input_sha256': 'three-prior-seasons'}}
        return self.record('fits', ident, 'posterior.npz')

    def derived(self, fit, leaf, rank=12):
        ident = {'fit_key': fit.name, 'scorer_source': cache.source_hash('loo_scoring.py'),
                 'reference_source': cache.source_hash('reference_config.py')}
        if leaf == 'scores':
            ident.update(reference_rank=rank, exact_loo=True,
                         exact_runner_source=cache.source_hash('fit_saved_season.py'),
                         exact_sampling_source=cache.source_hash('sampling_retry.py'))
        else:
            ident.update(game_id=101, reference_ranks=list(cache.REFERENCE_RANKS),
                         runner_source=cache.source_hash('fit_saved_season.py'),
                         sampling_source=cache.source_hash('sampling_retry.py'))
        return self.record(leaf, ident, 'merit.npz' if leaf == 'scores' else 'quantities.npz')

    def prune(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return cache.prune(self.root, self.inputs)

    def test_current_fit_all_references_and_exact_work_survive_old_week_cleanup(self):
        fit, old = self.fitted(), self.fitted(margin=3)
        keep = [fit, self.derived(fit, 'exact')]
        keep += [self.derived(fit, 'scores', r) for r in cache.REFERENCE_RANKS]
        discard = [old, self.derived(old, 'exact'), self.derived(old, 'scores')]
        before = {p: {f.name: f.read_bytes() for f in p.iterdir()} for p in keep}
        result = self.prune()
        self.assertEqual(result['removed_entries'], len(discard))
        self.assertLess(result['after']['total_bytes'], result['before']['total_bytes'])
        self.assertTrue(all(not p.exists() for p in discard))
        for p in keep:
            self.assertEqual(before[p], {f.name: f.read_bytes() for f in p.iterdir()})
        self.assertEqual(self.prune()['removed_entries'], 0)

    def test_preserves_matching_shared_home_prior_and_leaves_other_files_alone(self):
        identity = {'history_input_sha256': 'three-prior-seasons', 'fbs_ids': [1],
                    'specification': asdict(cache.HOME),
                    'source_sha256': digest(Path(cache.__file__).with_name('historical_home.py').read_text())}
        home = self.root / 'home'; home.mkdir()
        keep = home / (digest(identity) + '.json'); keep.write_text('saved home prior')
        stale = home / ('a'*64 + '.json'); stale.write_text('other history')
        untouched = [self.root / p for p in ('update-plan.json', 'venv/library', 'rankings/candidate.json',
                                            'assets/data/cfb/index.json', '_cfb_data/seasons/data.json')]
        for path in untouched:
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text('preserve')
        self.prune()
        self.assertEqual(keep.read_text(), 'saved home prior')
        self.assertFalse(stale.exists())
        self.assertTrue(all(path.read_text() == 'preserve' for path in untouched))

    def test_incomplete_and_unmatched_cache_entries_do_not_accumulate(self):
        fit = self.fitted()
        (fit / 'report.json').write_text('{incomplete')
        orphan = self.derived(fit, 'exact')
        self.prune()
        self.assertFalse(fit.exists()); self.assertFalse(orphan.exists())

    def test_report_does_not_follow_links_and_counts_directory_bytes(self):
        (self.root / 'fits').mkdir(); (self.root / 'fits' / 'array').write_bytes(b'12345')
        (self.root / 'plan').write_bytes(b'12')
        (self.root / 'link').symlink_to(self.root / 'fits', target_is_directory=True)
        report = bounded.storage_report(self.root)
        self.assertEqual(report['total_bytes'], 7)
        self.assertEqual(report['directory_bytes'], {'fits': 5, '(root files)': 2})

    def test_linked_cache_category_stops_cleanup_before_deleting(self):
        old = self.fitted(margin=3)
        outside = self.root / 'untouched'; outside.mkdir(); (outside / 'file').write_text('safe')
        (self.root / 'scores').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'linked cache'):
            self.prune()
        self.assertTrue(old.exists()); self.assertEqual((outside / 'file').read_text(), 'safe')

    def test_guard_refuses_to_start_when_already_full_and_reports_sizes(self):
        with patch.object(bounded, 'ROOT', self.root), patch.object(bounded, 'LIMIT', 100_000_001), \
                patch.object(bounded.sys, 'argv', ['run_bounded.py', 'fake']), \
                patch.object(bounded.subprocess, 'Popen') as launch, contextlib.redirect_stdout(io.StringIO()) as out:
            (self.root / 'plan').write_bytes(b'12')
            with self.assertRaisesRegex(RuntimeError, 'storage ceiling'):
                bounded.main()
            launch.assert_not_called()
            self.assertIn('directory_bytes', out.getvalue())

    def test_guard_checks_short_completed_commands_and_preserves_return_code(self):
        process = Mock(returncode=7); process.poll.return_value = 7
        with patch.object(bounded, 'ROOT', self.root), patch.object(bounded.sys, 'argv', ['run_bounded.py', 'fake']), \
                patch.object(bounded.subprocess, 'Popen', return_value=process), \
                patch.object(bounded, 'check_storage') as check:
            self.assertEqual(bounded.main(), 7)
            self.assertEqual([c.args[0] for c in check.call_args_list], ['before', 'after'])
            check.side_effect = [None, RuntimeError('storage ceiling')]
            with self.assertRaisesRegex(RuntimeError, 'storage ceiling'): bounded.main()

    def test_guard_terminates_active_child_on_storage_failure(self):
        process = Mock(pid=123); process.poll.return_value = None
        with patch.object(bounded, 'ROOT', self.root), patch.object(bounded.sys, 'argv', ['run_bounded.py', 'fake']), \
                patch.object(bounded.subprocess, 'Popen', return_value=process), \
                patch.object(bounded, 'check_storage', side_effect=[None, RuntimeError('storage ceiling')]), \
                patch.object(bounded.os, 'killpg') as kill:
            with self.assertRaisesRegex(RuntimeError, 'storage ceiling'): bounded.main()
            kill.assert_called_once_with(123, bounded.signal.SIGTERM)
            process.wait.assert_called_once_with(timeout=5)


if __name__ == '__main__':
    unittest.main()
