"""Focused numerical trace checks, no sampling or external data."""
import unittest
import numpy as np
from model import margin_model, strength_structure
from test_strength_structure import roster


class HierarchicalModelTests(unittest.TestCase):
    def test_posterior_export_includes_hierarchy_and_conference_distributions(self):
        import hashlib
        import json
        import os
        from pathlib import Path
        import tempfile
        from posterior_summary import attach, validate
        from sync_data import ROOT
        from test_publication import fixture
        result, inputs = fixture()
        inputs['fbs_indices'] = [0,1]
        samples = {k:np.full((4,2), v) for k,v in
                   dict(home_adv=3., sigma=14., nu=7., mu_fcs=-20., tau_conf=5.).items()}
        for k,v in dict(theta=[1.,0.,-20.], tau_division=[8.,12.], conference_effect=[2.,-2.], home_effect=[3.,0.,0.]).items():
            samples[k] = np.tile(v, (4,2,1))
        merit = np.tile([1.,0.,0.], (8,1)); sos = np.full((8,3), .5)
        for i,row in enumerate(result['teams']):
            for key,value in dict(merit=1-i, raw_rank=i+1, sos=.5).items():
                for suffix in ('_lo90','_hi90','_mean'): row[key+suffix] = value
        base = Path(os.environ.get('CFB_TEST_TMP', ROOT / '.codex-tmp' / 'cfb-update'))
        created = not base.exists(); base.mkdir(parents=True, exist_ok=True)
        if created: self.addCleanup(base.rmdir)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            task = Path(temporary)
            def save(folder, name, arrays, identity):
                folder.mkdir(parents=True); np.savez_compressed(folder/name, **arrays)
                checksum = hashlib.sha256((folder/name).read_bytes()).hexdigest()
                (folder/'report.json').write_text(json.dumps(dict(identity=identity,array_sha256=checksum)))
                return checksum
            fit_hash = save(task/'fits'/'fit', 'posterior.npz', samples, {'home_prior':result['home_prior']})
            merit_hash = save(task/'scores'/'score', 'merit.npz', dict(merit=merit,sos=sos),
                              dict(fit_key='fit',posterior_sha256=fit_hash,reference_rank=12))
            result['identity'].update(score_key='score',merit_sha256=merit_hash)
            attach(result, inputs, task)
        self.assertEqual(result['posterior']['parameters']['tau_fcs']['mean'],12.)
        self.assertEqual(result['posterior']['teams']['1']['conference_effect']['mean'],2.)
        self.assertEqual(result['posterior']['teams']['2']['conference_effect']['mean'],2.)
        conferences=result['posterior']['conferences']
        self.assertEqual(conferences['conferences'][0]['name'],'ACC')
        self.assertEqual(conferences['conferences'][0]['metrics']['roster']['strength']['mean'],0.)
        self.assertEqual(conferences['conferences'][0]['metrics']['roster']['p_best'],1.)
        del result['posterior']['parameters']['mu_fcs']
        with self.assertRaisesRegex(ValueError,'Missing model posterior'):
            validate(result)

    def test_noncentered_strength_likelihood_and_flat_hyperpriors(self):
        import jax
        import jax.numpy as jnp
        from numpyro.handlers import seed, substitute, trace
        jax.config.update('jax_enable_x64', True)
        structure = strength_structure(roster())
        z = jnp.arange(7.)/2
        w = jnp.array([1.,-.5,0.,.5,-1.])
        fixed = dict(theta_z=z, conference_z=w, tau_conf=6., mu_fcs=-25.,
                     tau_division=jnp.array([8.,12.]), home_z=jnp.zeros(5),
                     eta_sigma=np.log(6.), eta_nu=np.log(5.))
        def inspect(home, away, margin):
            return trace(seed(substitute(margin_model, data=fixed), rng_seed=42)).get_trace(
                7, jnp.array(home), jnp.array(away), jnp.zeros(len(home)), jnp.array(margin),
                host=jnp.zeros(len(home), dtype=int), home_prior=(jnp.zeros(5),jnp.eye(5)), structure=structure)
        full = inspect([0,1,2], [4,5,6], [10.,20.,30.])
        omitted = inspect([0,2], [4,6], [10.,30.])
        expected = np.array([0,0,0,0,-25,-25,-25]) + 6*np.asarray(w)[structure['conference']] + np.array([8,8,8,8,12,12,12])*np.asarray(z)
        np.testing.assert_allclose(full['theta']['value'], expected)
        np.testing.assert_array_equal(full['theta']['value'], omitted['theta']['value'])
        np.testing.assert_allclose(full['margin']['fn'].loc, expected[[0,1,2]]-expected[[4,5,6]])
        for key, values in [('mu_fcs',[-100.,0.,100.]),('tau_conf',[.1,1.,100.])]:
            np.testing.assert_array_equal(full[key]['fn'].log_prob(jnp.array(values)), 0.)
        np.testing.assert_array_equal(full['tau_division']['fn'].log_prob(jnp.array([8.,12.])), 0.)
        self.assertAlmostEqual(float(full['sigma']['value']), 14.)
        self.assertAlmostEqual(float(full['nu']['value']), 7.)


if __name__ == '__main__':
    unittest.main()
