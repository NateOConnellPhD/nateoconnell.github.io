// Pure numerical checks: no DOM, browser, network, sampling, or output files.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const api=require('../../assets/js/cfb-projections.js');
const n=1000,fill=x=>Array(n).fill(x);
const d={schema:'cfb-projections-v1',teams:{h:fill(0),a:fill(0)},home:{national:fill(0)},sigma:fill(1),nu:fill(8),
  noise:[fill(-1),fill(1)],lam:fill(1),quarterbacks:{h:{x:20,options:{one:20,two:-20}},a:{x:0,options:{one:0,two:2}}}};
api.validateDraws(d);
// A full-draw QB summary alone cannot replace the coefficient mean in a
// matchup whose power/margin are computed entirely from the saved sample.
const summaryOnly={...d,lambda_mean:2};
const sampled=api.matchup(summaryOnly,'h','a',true);
assert.equal(sampled.margin,20);assert.equal(sampled.parts.qbHome,20);
const withMeans={...summaryOnly,means:{teams:{h:0,a:0},home:{national:0}}};
const full=api.matchup(withMeans,'h','a',true);
assert.equal(full.margin,40);assert.equal(full.parts.qbHome,40);
for(const r of [sampled,full]) {
  const p=r.parts,total=p.home-p.away+p.qbHome-p.qbAway+p.national+p.stadium;
  assert.ok(Math.abs(total-r.margin)<1e-12,`QB components ${total} must sum to margin ${r.margin}`);
}
const first=api.matchup(d,'h','a',true),second=api.matchup(d,'h','a',true,1,{home:'two'});
const blend=weight=>api.matchup(d,'h','a',true,1,{home:{first:'one',second:'two',weight}});
assert.equal(blend(.25).margin,.25*first.margin+.75*second.margin);
assert.equal(blend(.25).pHome,.25*first.pHome+.75*second.pHome);
assert.deepEqual(blend(1).range80,first.range80);assert.deepEqual(blend(0).range95,second.range95);
assert.ok(blend(.5).range80[0]<-19&&blend(.5).range80[1]>19,'Mixture retains between-starter uncertainty');
assert.throws(()=>blend(1.1),/weight/);
const both=api.matchup(d,'h','a',true,1,{home:{first:'one',second:'two',weight:.5},away:{first:'one',second:'two',weight:.25}});
assert.equal(both.margin,-1.5);
const dir=path.resolve(__dirname,'../../assets/data/cfb/projections');
const index=JSON.parse(fs.readFileSync(path.join(dir,'index.json'))),row=index.snapshots.find(r=>r.id===index.latest);
const data=JSON.parse(fs.readFileSync(path.join(dir,row.file))),draws=api.validateDraws(JSON.parse(fs.readFileSync(path.join(dir,data.draws_file))));
let checked=0;
for(const g of data.games){const r=api.matchup(draws,g.home,g.away,g.neutral,g.ahead||1);assert.ok(Math.abs(r.margin-g.home_margin)<1e-8);checked++;}
// The supplied UCLA case is a scenario check, never a production override.
if(draws.quarterbacks?.['26']?.options?.['5142594']!==undefined) {
  const a=api.matchup(draws,'26','30',false,1,{home:'5092275'}),b=api.matchup(draws,'26','30',false,1,{home:'5142594'});
  const m=api.matchup(draws,'26','30',false,1,{home:{first:'5092275',second:'5142594',weight:.3}});
  for(const [x,y] of [[m.margin,.3*a.margin+.7*b.margin],[m.pHome,.3*a.pHome+.7*b.pHome],
      [m.scores.home.mean,.3*a.scores.home.mean+.7*b.scores.home.mean],
      [m.scores.away.mean,.3*a.scores.away.mean+.7*b.scores.away.mean]])assert.ok(Math.abs(x-y)<1e-10);
  assert.ok(a.margin>b.margin);assert.notEqual(a.scores.home.mean,b.scores.home.mean);
}
console.log(JSON.stringify({mixture_checks:'passed',saved_default_margins_checked:checked}));
