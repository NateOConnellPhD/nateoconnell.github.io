"""Small four-chain execution check, not convergence or season validation.

Runs only when invoked explicitly. Keeps arrays in memory and uses the caller's
task-local cache environment. No downloads, data-provider calls or publication.
"""
import json
import time
import numpy as np
from model import fit, strength_structure


def main():
    teams = [dict(id=i+1, name=f'Team {i}', classification='fbs' if i<8 else 'fcs',
                  conference=f'Conference {i//4}') for i in range(16)]
    structure = strength_structure(teams)
    rng = np.random.default_rng(20261121)
    theta = np.r_[rng.normal(0,8,8), rng.normal(-25,10,8)]
    pairs = [(i,j) for i in range(16) for j in range(i+1,16)]
    home = [i for i,j in pairs]; away = [j for i,j in pairs]
    venue = [int(k%5 != 0) for k in range(len(pairs))]
    margin = (theta[home]-theta[away]+3*np.asarray(venue)+12*rng.standard_t(7,len(pairs))).tolist()
    prior = dict(mean=[3.]+[0.]*8, chol=(np.eye(9)*.5).tolist())
    started = time.monotonic()
    sampler = fit(16, home, away, venue, margin, structure=structure,
                  host=[i+1 if i<8 else 0 for i in home], home_prior=prior,
                  seed=20261121, warmup=100, draws=50)
    samples = sampler.get_samples(group_by_chain=True)
    required = {'theta','theta_z','mu_fcs','tau_division','tau_conf','conference_effect','conference_z',
                'home_effect','home_adv','home_z','sigma','nu','eta_sigma','eta_nu'}
    if not required <= samples.keys() or samples['theta'].shape != (4,50,16):
        raise ValueError('Missing posterior fields or sequential-chain dimensions')
    if any(not np.isfinite(v).all() for v in samples.values()):
        raise ValueError('Nonfinite synthetic posterior draw')
    extra = sampler.get_extra_fields(group_by_chain=True)
    print(json.dumps(dict(chains=4, warmup=100, draws_per_chain=50,
        seconds=round(time.monotonic()-started,2), finite_draws=True,
        divergences=int(np.sum(extra['diverging'])),
        note='Execution smoke check only; too short to validate convergence or early-season calibration.')))


if __name__ == '__main__':
    main()
