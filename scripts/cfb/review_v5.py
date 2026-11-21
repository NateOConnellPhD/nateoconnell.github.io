"""Replay the owner's corrected FCS handoff without HMC, API calls or downloads.

Only derived comparison reports may be written, with --output explicitly set.
The supplied NPZ and source data remain private and are never copied to Git.
"""
import argparse
import ast
import csv
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import struct
import zipfile

from ranking_policy_v5 import CANONICAL, prepare_policy, order_policy


def array(archive, name):
    entry = archive.getinfo(name + '.npy')
    if entry.file_size > 8_000_000: raise ValueError('Unexpectedly large fixture array')
    f = io.BytesIO(archive.read(entry))
    signature = f.read(8)
    if signature[:6] != b'\x93NUMPY' or signature[6] not in (1, 2): raise ValueError('Unsupported NPY')
    size = 2 if signature[6] == 1 else 4
    length = int.from_bytes(f.read(size), 'little')
    header = ast.literal_eval(f.read(length).decode('latin1'))
    if header['fortran_order']: raise ValueError('Expected row-major fixture')
    body = f.read(); dtype = header['descr']
    if dtype == '<f8': values = [v[0] for v in struct.iter_unpack('<d', body)]
    elif dtype.startswith('<U'):
        width = 4 * int(dtype[2:]); values = [body[i:i+width].decode('utf-32-le').rstrip('\0') for i in range(0, len(body), width)]
    else: raise ValueError('Unsupported fixture dtype; object arrays are never loaded')
    return header['shape'], values


def csv_rows(path):
    with path.open(newline='') as handle: return list(csv.DictReader(handle))


def load(folder):
    results = folder / 'cfb_fcs_extension/results'
    npz = results / '2026_merit_draws.npz'
    with zipfile.ZipFile(npz) as z:
        _, names = array(z, 'teams')
        (count, n), flat = array(z, 'merit')
    if n != len(names) or len(flat) != n*count: raise ValueError('Malformed draw dimensions')
    columns = [flat[i::n] for i in range(n)]
    means = [sum(c)/count for c in columns]
    p = [[0.]*n for _ in names]
    for i in range(n):
        for j in range(i+1,n):
            p[i][j] = sum(a>b for a,b in zip(columns[i],columns[j]))/count
            p[j][i] = sum(a>b for a,b in zip(columns[j],columns[i]))/count
    roster, games = {}, []
    for row in csv_rows(results/'2026_FBS_scored_games.csv'):
        for side in ('home','away'):
            t=dict(id=int(row[side+'_id']),name=row[side+'_team'],conference=row[side+'_conference'],classification=row[side+'_division'])
            if t['name'] in roster and roster[t['name']]!=t: raise ValueError('Inconsistent fixture roster')
            roster[t['name']]=t
        games.append(dict(id=int(row['game_id']),season=int(row['season']),season_type=row['season_type'],
            completed=row['completed']=='True',eligible=True,home_id=int(row['home_id']),away_id=int(row['away_id']),
            home_points=int(row['home_points']),away_points=int(row['away_points'])))
    baseline={r['team']:r for r in csv_rows(results/'2026_margin_of_merit_all_teams.csv')}
    expected_p=csv_rows(results/'2026_pairwise_merit_probabilities.csv')
    for i,name in enumerate(names):
        if abs(means[i]-float(baseline[name]['merit_mean']))>1e-12: raise ValueError('Saved mean mismatch')
        if expected_p[i]['']!=name: raise ValueError('Saved probability roster mismatch')
        for j,other in enumerate(names):
            if i!=j and abs(p[i][j]-float(expected_p[i][other]))>1e-12: raise ValueError('Saved probability mismatch')
    opponents=sorted((t for t in roster.values() if t['classification']=='fcs'),key=lambda t:t['id'])
    state=prepare_policy([roster[name] for name in names],games,means,p,season=2026,opponents=opponents)
    for i,name in enumerate(names):
        if [state['wins'][i],state['losses'][i]]!=[int(baseline[name]['W']),int(baseline[name]['L'])]:
            raise ValueError('Overall record mismatch')
    return state,baseline,dict(merit_draws_sha256=hashlib.sha256(npz.read_bytes()).hexdigest(),draws=count,
        teams=n,scored_games=len(games),baseline_verified='All merit means, strict pair probabilities and overall records reproduced from supplied draws and scores.')


def review(folder):
    state,baseline,provenance=load(folder)
    names={t['id']:t['name'] for t in state['teams']}
    windows={}
    for w in (0,1,2,3):
        setting=replace(CANONICAL,proximity=w)
        payload=state['payload']
        s=prepare_policy(payload['teams'],payload['games'],payload['means'],payload['probabilities'],
            season=2026,opponents=payload['opponents'],specification=setting)
        r=order_policy(s)
        windows[str(w)]={'order':r['order'],'optimization':r['optimization'],
                        'overridden':[a for a in r['audit'] if a['status']=='overridden_by_global_objective']}
        if w==2: official=r
    rows=[]
    for rank,ident in enumerate(official['order'],1):
        name=names[ident]; old=baseline[name]
        rows.append(dict(id=ident,name=name,rank=rank,raw_rank=int(old['raw_rank']),v4_rank=int(old['rank']),
            change_from_v4=int(old['rank'])-rank,merit_mean=float(old['merit_mean']),wins=int(old['W']),losses=int(old['L']),
            explanation='Unchanged' if int(old['rank'])==rank else 'Exact global H2H/common/merit/inversion ordering; see pair requirements and objective certificate.',
            requirement_indices=[i for i,a in enumerate(official['audit']) if ident in (a['winner_id'],a['loser_id']) and
                (a['type'] in ('head_to_head','common_opponents') or a['status']=='overridden_by_global_objective')]))
    return dict(schema='margin-of-merit-v5-review-v1',snapshot='Supplied frozen games through November 19, 2026; includes a partial week. Not a completed-week publication.',
        provenance=provenance,specification=official['specification'],teams=rows,optimization=official['optimization'],
        sensitivity=windows,audit=official['audit'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path); parser.add_argument('--output',type=Path)
    args=parser.parse_args(); result=review(args.folder)
    print(json.dumps({'verified':result['provenance'],'optimization':result['optimization'],
                     'changed_teams':[{k:r[k] for k in ('name','v4_rank','rank')} for r in result['teams'] if r['change_from_v4']]}))
    if args.output:
        args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')


if __name__=='__main__': main()
