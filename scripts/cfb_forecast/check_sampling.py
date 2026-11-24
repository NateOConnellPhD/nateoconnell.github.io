"""Diagnose one real forecast fit without publishing or fetching data.

Outputs only small diagnostic summaries and scalar traces under .codex-tmp.
Use the same seed and inputs when comparing target acceptance settings.
"""
import argparse
import json
from pathlib import Path
import time

from publish import ROOT, source, forecast


def run(args):
    import arviz as az
    import numpy as np
    from cfb_forecast.home import load_or_estimate
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT / '.codex-tmp'):
        raise ValueError('Diagnostic output must stay under the project .codex-tmp directory')
    output.mkdir(parents=True, exist_ok=True)
    inputs, prior, expectancy, games, _, key = source.load(args.season, forecast_week=args.week)
    if args.qb_covariates:
        # Reference-window validation when the handoff supplies frozen covariates.
        # This is not the production data loader and never publishes a snapshot.
        import csv
        if args.week is None or args.export: raise ValueError('Frozen QB covariates require a historical week and no export')
        names={str(t['id']):t['name'] for t in inputs['teams']}
        with Path(args.qb_covariates).open() as stream:
            rows=[r for r in csv.DictReader(stream) if int(r['window'])==args.week]
        x={(int(r['game_id']),r['team']):float(r['x_start']) for r in rows}
        if not x: raise ValueError('No supplied QB covariates for this window')
        inputs['qbx']=[x.get((g['id'],names[str(g['home_id'])]),0.)-x.get((g['id'],names[str(g['away_id'])]),0.) for g in inputs['games']]
    home = load_or_estimate(inputs, output / 'home')
    target, _, _ = forecast.efficiency_target(inputs['data']['margin'], expectancy)
    label = f'accept-{args.target_accept}-seed-{args.seed}-warm-{args.warmup}-draws-{args.draws}'
    if (output / (label+'.json')).exists(): raise ValueError('Diagnostic result already exists; choose another run')
    print(json.dumps({'phase':'sampling','season':args.season,'games':len(inputs['games']),
        'teams':len(inputs['teams']),'training_key':key,'settings':label}), flush=True)
    started = time.monotonic()
    sampler = forecast.fit(inputs, prior, home, prior['fcs_gap'], target, seed=args.seed,
        warmup=args.warmup, draws=args.draws, target_accept=args.target_accept)
    sampling_seconds = time.monotonic()-started
    all_samples = {k:np.asarray(v) for k,v in sampler.get_samples(group_by_chain=True).items()}
    extra = {k:np.asarray(v) for k,v in sampler.get_extra_fields(group_by_chain=True).items()}
    scalar = {k:v for k,v in all_samples.items() if v.ndim==2 or k in ('tau','mu_free')}
    np.savez_compressed(output / (label+'.npz'), **scalar, **{'extra_'+k:v for k,v in extra.items()})
    samples, diagnostics, _ = forecast.diagnose(sampler)
    # Retain coordinate names for the worst mixing diagnostics, not only a max.
    checked = {k:(v[...,1:] if k=='walk' else v) for k,v in all_samples.items()}
    idata = az.from_dict(posterior=checked)
    worst = {}
    for name, fn, kwargs, reverse in [('rhat',az.rhat,{'method':'rank'},True),
            ('bulk_ess',az.ess,{'method':'bulk'},False),('tail_ess',az.ess,{'method':'tail'},False)]:
        values=[]
        for variable,a in fn(idata,**kwargs).data_vars.items():
            a=np.asarray(a)
            for ix in np.ndindex(a.shape): values.append({'parameter':variable,'coordinate':list(ix),'value':float(a[ix])})
        worst[name]=sorted(values,key=lambda r:r['value'],reverse=reverse)[:5]
    last=all_samples.get('theta_last',all_samples['theta'])
    centered=last  # supplied rating scale; never recenter the posterior
    mcse=np.asarray(az.mcse(az.from_dict(posterior={'power':centered}),method='mean')['power'])
    result={'training_key':key,'settings':{'target_accept':args.target_accept,'seed':args.seed,
        'warmup':args.warmup,'draws':args.draws,'chains':4},'sampling_seconds':sampling_seconds,
        'diagnostics':diagnostics,'worst_mixing':worst,
        'power':{str(t['id']):{'name':t['name'],'mean':float(centered[:,:,i].mean()),
            'sd':float(centered[:,:,i].std()),'mcse':float(mcse[i])} for i,t in enumerate(inputs['teams'])}}
    (output / (label+'.json')).write_text(json.dumps(result,allow_nan=False,indent=2)+'\n')
    if args.export and diagnostics['sampling_checks_passed']:
        from publish import request, make_snapshot, export
        _, _, _, games, observed, current_key, input_key = request(args.season)
        if current_key != key: raise ValueError('Inputs changed during the diagnostic fit')
        arrays, rescale = forecast.prediction_arrays(samples, inputs, target)
        _, scale, count = forecast.efficiency_target(inputs['data']['margin'], expectancy)
        metadata={'fit_key':'verified-local-'+label,'fit_reused':False,'prior_only':False,
            'diagnostics':diagnostics,'noise_rescale':rescale,'efficiency_scale':scale,'efficiency_games':count,
            'prior_sd_posterior':float(samples['s_prev'].mean()),'drift_sd_posterior':float(samples['q'].mean())}
        public, browser = make_snapshot(inputs, prior, expectancy, games, observed, input_key, arrays, home, metadata)
        export.write(public, browser, output/'public')
    print(json.dumps({'sampling_seconds':sampling_seconds,'diagnostics':diagnostics,'worst_mixing':worst}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--season',type=int,default=2026)
    p.add_argument('--week',type=int)
    p.add_argument('--qb-covariates',help='Supplied x_start CSV for one historical validation window only')
    p.add_argument('--target-accept',type=float,required=True)
    p.add_argument('--warmup',type=int,default=1000)
    p.add_argument('--draws',type=int,default=1000)
    p.add_argument('--seed',type=int,default=2026)
    p.add_argument('--output',required=True)
    p.add_argument('--export',action='store_true',help='Write a passing snapshot only inside the diagnostic output directory')
    run(p.parse_args())
