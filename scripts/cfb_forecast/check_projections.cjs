// Numerical and offline controller checks, without a browser or network.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const api=require('../../assets/js/cfb-projections.js');
const dir=path.resolve(__dirname,'../../assets/data/cfb/projections');
const index=JSON.parse(fs.readFileSync(path.join(dir,'index.json'))),row=index.snapshots.find(r=>r.id===index.latest);
const data=JSON.parse(fs.readFileSync(path.join(dir,row.file))),draws=api.validateDraws(JSON.parse(fs.readFileSync(path.join(dir,data.draws_file))));
assert.equal(api.tcdf(0,7),.5);
assert.ok(Math.abs(api.tcdf(1,3)-.8044988905221147)<1e-10);
assert.ok(Math.abs(api.tcdf(2,10)-.9633059826146299)<1e-10);
for(const nu of [2.01,3,7,30,1000])for(const x of [-100,-10,-1,0,1,10,100]) {
  const p=api.tcdf(x,nu);assert.ok(p>=0&&p<=1);assert.ok(Math.abs(p+api.tcdf(-x,nu)-1)<1e-12);
}
const a=data.ratings[0].id,b=data.ratings[1].id;
const neutral=api.matchup(draws,a,b,true),reverse=api.matchup(draws,b,a,true),home=api.matchup(draws,a,b,false);
assert.ok(neutral.expected95[0]<=neutral.expected80[0]&&neutral.expected95[1]>=neutral.expected80[1]);
const positions=api.strengthPositions({sigma:Array(100).fill(1),teams:{a:Array(95).fill(2).concat(Array(5).fill(0)),b:Array(100).fill(1),fcs:Array(100).fill(100)}},['a','b']);
assert.deepEqual(positions.a[80],[1,1]);assert.deepEqual(positions.a[95],[1,2]);
assert.deepEqual(positions.b[80],[2,2]);assert.deepEqual(positions.b[95],[1,2]);
assert.ok(Math.abs(neutral.pHome+reverse.pHome-1)<1e-12);
assert.ok(Math.abs(neutral.margin+reverse.margin)<1e-12);
assert.ok(Math.abs(home.homeLine+home.margin)<1e-12);
assert.throws(()=>api.matchup(draws,a,a,true),/different teams/);
assert.throws(()=>api.validateDraws({...draws,sigma:[1]}),/Invalid|align/);
let maxProbabilityError=0,maxMarginError=0;
for(const g of data.games){const m=api.matchup(draws,g.home,g.away,g.neutral,g.ahead||1);maxProbabilityError=Math.max(maxProbabilityError,Math.abs(m.pHome-g.p_home));maxMarginError=Math.max(maxMarginError,Math.abs(m.margin-g.home_margin));}
assert.ok(Number.isFinite(maxProbabilityError),'Thinned probabilities must be finite');
assert.ok(maxMarginError<1e-8,`Full-draw means must preserve lines: ${maxMarginError}`);

class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.handlers={};this.dataset={};this.attrs={};this.hidden=false;this.textContent='';this._value='';}
  set value(v){this._value=String(v);}get value(){return this._value;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;if(this.tag==='select')this.value=nodes[0]?.attrs.value??'';}
  setAttribute(k,v){this.attrs[k]=String(v);if(k==='value')this.value=v;}
  addEventListener(k,fn){this.handlers[k]=fn;}
  focus(){}scrollIntoView(){}
}
async function controller(hash='',overrides={}) {
  // Only expose hooks present in the shipped template. Inventing an element for
  // every selector concealed accesses to controls that had already been removed.
  const template=fs.readFileSync(path.resolve(__dirname,'../../_includes/cfb-projections.html'),'utf8');
  const nodes=new Map();
  for(const [,tag,attrs] of template.matchAll(/<([a-z][\w-]*)\b([^>]*)>/g)) {
    for(const [,key] of attrs.matchAll(/\bdata-projection-([\w-]+)(?=[\s=>]|$)/g)) {
      const element=new Element(tag);element.hidden=/\bhidden\b/.test(attrs);nodes.set(key,element);
    }
  }
  const get=k=>nodes.get(k)||null;
  for(const [,attrs,content] of template.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)) {
    const key=attrs.match(/\bdata-projection-([\w-]+)/)?.[1];if(!key)continue;
    const options=[...content.matchAll(/<option\b([^>]*)>([^<]*)<\/option>/g)].map(([,a,text])=>{
      const option=new Element('option');option.textContent=text;option.setAttribute('value',a.match(/value="([^"]*)"/)?.[1]??text);return option;
    });
    get(key).replaceChildren(...options);
  }
  get('limit').value='all';const root=new Element(),main=new Element();root.dataset.index='/assets/data/cfb/projections/index.json';
  root.querySelector=s=>get(s.match(/data-projection-([^\]]+)/)[1]);
  const buttons=['merit','projections'].map(name=>{const b=new Element('button');b.dataset.cfbProductTab=name;return b;});
  const viewButtons=['power','games','compare','method'].map(name=>{const b=new Element('button');b.dataset.projectionView=name;return b;});
  const viewPanels=['power','games','compare','method'].map(name=>{const p=new Element();p.dataset.projectionPanel=name;return p;});
  const requests=[],events=[];
  const doc={querySelector:s=>s.includes('product-panel')?main:root,querySelectorAll:s=>s.includes('product-tab')?buttons:s.includes('projection-view')?viewButtons:s.includes('projection-panel')?viewPanels:[],
    createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),createTextNode:text=>({textContent:text}),dispatchEvent:e=>events.push(e.type)};
  const location={href:`https://example.test/blog/cfb/${hash}`,hash,pathname:'/blog/cfb/',search:''};
  const context={document:doc,location,URL,Event,AbortController,setTimeout,clearTimeout,console,
    history:{replaceState:(_,__,url)=>{location.hash=new URL(url,location.href).hash;}},
    fetch:async url=>{const file=path.basename(String(url));requests.push(file);return {ok:true,json:async()=>overrides[file]||JSON.parse(fs.readFileSync(path.join(dir,file)))};}};
  context.window=context;context.addEventListener=()=>{};
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname,'../../assets/js/cfb-projections.js'),'utf8'),context);
  const settle=async()=>{for(let i=0;i<5;i++)await new Promise(setImmediate);};await settle();
  return {get,main,root,buttons,viewButtons,viewPanels,requests,events,settle};
}
(async()=>{
  const p=await controller();assert.equal(p.requests.length,0,'Merit view must not download projections');
  p.buttons[1].handlers.click();await p.settle();assert.equal(p.main.hidden,true);assert.equal(p.root.hidden,false);
  assert.equal(p.get('status').textContent,'');assert.equal(p.get('content').hidden,false);
  assert.equal(p.get('matchup-result').hidden,false);assert.match(p.get('line').textContent,/by .* points|Evenly matched/);
  assert.equal(p.get('coverage').value,'80');assert.match(p.get('range').textContent,/ to /);
  assert.match(p.get('range-label').textContent,/80%/);
  assert.ok(p.get('games').children[0].children[0].children[0].children.every(h=>!(/market|line|opener/i.test(h.textContent))));
  assert.ok(p.get('strength-chart').children.length>0);assert.ok(p.get('margin-chart').children.length>0);
  assert.equal(p.get('powers').children[0].children[1].children.length,data.ratings.length);
  assert.deepEqual(p.viewPanels.map(x=>x.hidden),[false,true,true,true]);
  p.viewButtons[1].handlers.click();assert.deepEqual(p.viewPanels.map(x=>x.hidden),[true,false,true,true]);
  p.get('games').children[0].children[1].children[0].children[1].children[0].handlers.click();
  assert.deepEqual(p.viewPanels.map(x=>x.hidden),[true,true,false,true]);
  p.viewButtons[0].handlers.click();
  p.get('powers').children[0].children[1].children[0].children[1].children[0].handlers.click();
  assert.equal(p.get('home').value,data.ratings[0].id);assert.equal(p.get('site').value,'neutral');
  assert.deepEqual(p.viewPanels.map(x=>x.hidden),[true,true,false,true]);
  p.viewButtons[2].handlers.keydown({key:'Home',preventDefault(){}});
  assert.equal(p.viewButtons[0].attrs['aria-selected'],'true');
  const before=p.requests.length;p.get('swap').handlers.click();p.get('site').value='neutral';p.get('site').handlers.change();
  p.buttons[0].handlers.click();p.buttons[1].handlers.click();await p.settle();assert.equal(p.requests.length,before,'Changing teams/tabs must reuse static data');
  p.get('away').value=p.get('home').value;p.get('away').handlers.change();assert.match(p.get('matchup-error').textContent,/different/);
  const direct=await controller('#projections');assert.equal(direct.main.hidden,true);assert.ok(direct.requests.length>0);
  assert.equal(direct.get('home-qb').value,'');assert.equal(direct.get('away-qb').value,'');
  assert.equal(direct.get('qb-scenarios').hidden,!data.quarterbacks);
  assert.equal(direct.get('status').textContent,'');assert.equal(direct.get('content').hidden,false);
  assert.equal(direct.get('matchup-error').textContent,'');assert.equal(direct.get('matchup-result').hidden,false);
  for(const snapshot of index.snapshots) {
    direct.get('snapshot').value=snapshot.id;
    await direct.get('snapshot').handlers.change();await direct.settle();
    assert.equal(direct.get('status').textContent,'',`Snapshot ${snapshot.id} must load`);
    assert.equal(direct.get('content').hidden,false);
    assert.equal(direct.get('matchup-error').textContent,'');assert.equal(direct.get('matchup-result').hidden,false);
  }
  direct.get('reload').handlers.click();await direct.settle();
  assert.equal(direct.get('snapshot').value,index.latest);assert.equal(direct.get('status').textContent,'');
  const headers=element=>element.children[0].children[0].children[0].children.map(n=>n.textContent);
  const rows=element=>element.children[0].children[1].children.map(r=>r.children.map(c=>c.children[0].textContent));
  const report=JSON.parse(fs.readFileSync(path.join(dir,'backtest.json')));
  const checkAccuracy=(view,period)=>{
    const overall=report[period].week.find(r=>r.group==='all');
    assert.equal(view.get('accuracy-summary').hidden,false);
    for(const limit of [3,7,10,14]) {
      assert.equal(view.get('within-'+limit).textContent,`${(100*overall.within_points[limit]/overall.n).toFixed(1)}%`);
      assert.equal(view.get('within-'+limit+'-count').textContent,`${overall.within_points[limit].toLocaleString()} of ${overall.n.toLocaleString()} games`);
    }
    assert.deepEqual(headers(view.get('evaluation')),['Week','Games','Within 3 points','Within 7 points','Within 10 points','Within 14 points']);
    if(period==='holdout')assert.deepEqual(rows(view.get('evaluation')).map(r=>r[0]),Array.from({length:12},(_,i)=>`Week ${i+1}`).concat('All games'));
  };
  assert.equal(direct.get('eval-period').value,'holdout');assert.equal(direct.get('eval-group'),null);
  checkAccuracy(direct,'holdout');
  const originalRange=direct.get('range').textContent,originalLine=direct.get('line').textContent;
  const originalProbability=direct.get('home-chance').textContent,originalRequests=direct.requests.length;
  const originalPower=rows(direct.get('powers'))[0][5];
  direct.get('coverage').value='95';direct.get('coverage').handlers.change();
  assert.equal(direct.requests.length,originalRequests,'Changing interval coverage must not fetch or fit');
  assert.match(direct.get('range-label').textContent,/95%/);assert.notEqual(direct.get('range').textContent,originalRange);
  assert.equal(direct.get('line').textContent,originalLine);assert.equal(direct.get('home-chance').textContent,originalProbability);
  assert.ok(headers(direct.get('powers')).includes('95% interval'));assert.notEqual(rows(direct.get('powers'))[0][5],originalPower);
  assert.match(direct.get('error-range-label').textContent,/95%/);assert.match(direct.get('error-bias-note').textContent,/95% confidence/);
  checkAccuracy(direct,'holdout');
  assert.ok(headers(direct.get('evaluation-signed')).includes('Middle 95% of errors (pts)'));
  assert.ok(headers(direct.get('evaluation-technical')).includes('95% confidence interval for MAE'));
  await direct.get('snapshot').handlers.change();await direct.settle();
  assert.equal(direct.get('coverage').value,'95');assert.match(direct.get('range-label').textContent,/95%/);
  direct.get('reload').handlers.click();await direct.settle();
  assert.equal(direct.get('coverage').value,'95');assert.equal(direct.get('status').textContent,'');
  direct.get('coverage').value='80';direct.get('coverage').handlers.change();
  assert.equal(direct.get('range').textContent,originalRange);assert.equal(rows(direct.get('powers'))[0][5],originalPower);
  // Exercise the new drift/details controller using in-memory data, not a browser.
  const dynamic={...draws,last:draws.teams,drift:Object.fromEntries(Object.entries(draws.teams).map(([id,x],j)=>[id,x.map((_,i)=>(j%2?1:-1)*(i/x.length-.5)*2)]))};
  delete dynamic.teams;delete dynamic.means;api.validateDraws(dynamic);
  const game={...data.games[0],ahead:4}, result=api.matchup(dynamic,game.home,game.away,game.neutral,4);
  Object.assign(game,{home_margin:result.margin,home_line:result.homeLine,p_home:result.pHome,margin_lo80:result.range80[0],margin_hi80:result.range80[1]});
  const part=result.parts,partsTotal=part.home-part.away+part.qbHome-part.qbAway+part.national+part.stadium;
  assert.ok(Math.abs(partsTotal-result.margin)<1e-9,`Sampled-draw components (${partsTotal}) must sum to the sampled margin (${result.margin})`);
  const fixture={...data,games:[game],draws_file:'draws-fixture.json',meta:{...data.meta,model:'forecast-v7'},
    team_details:Object.fromEntries([game.home,game.away].map(id=>[id,{path:[{week:1,mean:5,sd:2},{week:2,mean:6,sd:1.5}],games:[]}]))};
  dynamic.scores={version:'conditional-scores-1',intercept:dynamic.sigma.map(()=>20),slope:dynamic.sigma.map(()=>-3),
    scale:dynamic.sigma.map(()=>10),teams:Object.fromEntries(Object.keys(dynamic.teams).map(id=>[id,dynamic.sigma.map(()=>0)])),
    uniform:[dynamic.sigma.map(()=>.2),dynamic.sigma.map(()=>.8)]};
  game.scores=api.matchup(api.validateDraws(dynamic),game.home,game.away,game.neutral,4).scores;
  const modern=await controller('#projections',{'index.json':{...index,latest:'fixture',snapshots:[{...row,id:'fixture',file:'forecast-fixture.json'}]},'forecast-fixture.json':fixture,'draws-fixture.json':dynamic});
  assert.equal(modern.get('status').textContent,'');assert.equal(modern.get('details-card').hidden,false);
  assert.equal(modern.get('team-details').children.length,2);assert.equal(modern.get('horizon').value,'4');
  assert.equal(modern.get('line-parts').children[0].children[1].children.length,7);
  assert.equal(modern.get('scores').hidden,false);assert.equal(modern.get('score-status').textContent,'');
  assert.ok(modern.get('score-chart').children.length>0);
  assert.equal(modern.get('score-summary').children[0].children[1].children.length,2);
  assert.ok(Number.isFinite(Number(modern.get('home-score').textContent)));
  assert.ok(modern.get('games').children[0].children[0].children[0].children.some(h=>/Home points/.test(h.textContent)));
  assert.deepEqual(headers(modern.get('games')),['Date','Matchup','Home points · mean (80% range)',
    'Away points · mean (80% range)','Predicted margin','Home win','Away win']);
  assert.equal(rows(modern.get('games'))[0][4],modern.get('line').textContent);
  const scoreBefore=modern.get('home-score').textContent,scoreRangeBefore=rows(modern.get('score-summary'))[0][3];
  const gameRangeBefore=rows(modern.get('games'))[0][2],requestsBefore=modern.requests.length;
  modern.get('coverage').value='95';modern.get('coverage').handlers.change();
  assert.ok(headers(modern.get('score-summary')).includes('95% predictive range'));
  assert.ok(headers(modern.get('games')).includes('Home points · mean (95% range)'));
  assert.equal(modern.get('home-score').textContent,scoreBefore);
  assert.notEqual(rows(modern.get('score-summary'))[0][3],scoreRangeBefore);assert.notEqual(rows(modern.get('games'))[0][2],gameRangeBefore);
  assert.match(modern.get('score-chart').children[1].textContent,/95% range/);
  assert.equal(modern.requests.length,requestsBefore);
  modern.get('coverage').value='80';modern.get('coverage').handlers.change();
  assert.equal(rows(modern.get('score-summary'))[0][3],scoreRangeBefore);assert.equal(rows(modern.get('games'))[0][2],gameRangeBefore);
  const qbDraws={...dynamic,lam:dynamic.sigma.map((_,i)=>.5+i/dynamic.sigma.length),lambda_mean:1.,
    quarterbacks:{[game.home]:{x:2,options:{backup:-4}},[game.away]:{x:-1,options:{backup:3}}}};
  const base=api.matchup(qbDraws,game.home,game.away,true,1,{home:'mix',away:'mix'});
  const starter=api.matchup(qbDraws,game.home,game.away,true,1);
  const backup=api.matchup(qbDraws,game.home,game.away,true,1,{home:'backup'});
  assert.ok(starter.margin>base.margin&&backup.margin<base.margin);
  assert.ok(starter.pHome>base.pHome&&backup.pHome<base.pHome);
  const sampledLambda=qbDraws.lam.reduce((a,b)=>a+b,0)/qbDraws.lam.length;
  assert.ok(Math.abs(backup.parts.qbHome+4*sampledLambda)<1e-12,'Sampled-draw QB component must use the sampled coefficient mean');
  const reverseQB=api.matchup(qbDraws,game.away,game.home,true,1);
  assert.ok(Math.abs(starter.pHome+reverseQB.pHome-1)<1e-12);
  assert.throws(()=>api.matchup(qbDraws,game.home,game.away,true,1,{home:'unknown'}),/Unknown quarterback/);
  modern.get('eval-period').value='development';modern.get('eval-period').handlers.change();checkAccuracy(modern,'development');
  modern.get('eval-period').value='holdout';modern.get('eval-period').handlers.change();assert.match(modern.get('backtest-summary').textContent,/2026/);
  checkAccuracy(modern,'holdout');
  console.log(JSON.stringify({checks:'projection probabilities, venue, signs, payload integrity, tab isolation, charts, caching, 80/95 interval selection',games:data.games.length,maxProbabilityError,maxMarginError}));
})().catch(e=>{console.error(e);process.exitCode=1;});
