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
  const nodes=new Map(),get=k=>{if(!nodes.has(k))nodes.set(k,new Element(['snapshot','home','away','site','week','conference','limit'].includes(k)?'select':'div'));return nodes.get(k);};
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
  assert.match(p.get('range95').textContent,/ to /);
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
  // Exercise the new drift/details controller using in-memory data, not a browser.
  const dynamic={...draws,last:draws.teams,drift:Object.fromEntries(Object.entries(draws.teams).map(([id,x],j)=>[id,x.map((_,i)=>(j%2?1:-1)*(i/x.length-.5)*2)]))};
  delete dynamic.teams;delete dynamic.means;api.validateDraws(dynamic);
  const game={...data.games[0],ahead:4}, result=api.matchup(dynamic,game.home,game.away,game.neutral,4);
  Object.assign(game,{home_margin:result.margin,home_line:result.homeLine,p_home:result.pHome,margin_lo80:result.range80[0],margin_hi80:result.range80[1]});
  const part=result.parts;assert.ok(Math.abs(part.home-part.away+part.national+part.stadium-result.margin)<1e-9);
  const fixture={...data,games:[game],draws_file:'draws-fixture.json',meta:{...data.meta,model:'forecast-v7'},
    team_details:Object.fromEntries([game.home,game.away].map(id=>[id,{path:[{week:1,mean:5,sd:2},{week:2,mean:6,sd:1.5}],games:[]}]))};
  const modern=await controller('#projections',{'index.json':{...index,latest:'fixture',snapshots:[{...row,id:'fixture',file:'forecast-fixture.json'}]},'forecast-fixture.json':fixture,'draws-fixture.json':dynamic});
  assert.equal(modern.get('status').textContent,'');assert.equal(modern.get('details-card').hidden,false);
  assert.equal(modern.get('team-details').children.length,2);assert.equal(modern.get('horizon').value,'4');
  assert.equal(modern.get('line-parts').children[0].children[1].children.length,7);
  const qbDraws={...dynamic,lam:dynamic.sigma.map((_,i)=>.5+i/dynamic.sigma.length),lambda_mean:1.,
    quarterbacks:{[game.home]:{x:2,options:{backup:-4}},[game.away]:{x:-1,options:{backup:3}}}};
  const base=api.matchup(qbDraws,game.home,game.away,true,1,{home:'mix',away:'mix'});
  const starter=api.matchup(qbDraws,game.home,game.away,true,1);
  const backup=api.matchup(qbDraws,game.home,game.away,true,1,{home:'backup'});
  assert.ok(starter.margin>base.margin&&backup.margin<base.margin);
  assert.ok(starter.pHome>base.pHome&&backup.pHome<base.pHome);
  assert.ok(Math.abs(backup.parts.qbHome+4)<1e-12);
  const reverseQB=api.matchup(qbDraws,game.away,game.home,true,1);
  assert.ok(Math.abs(starter.pHome+reverseQB.pHome-1)<1e-12);
  assert.throws(()=>api.matchup(qbDraws,game.home,game.away,true,1,{home:'unknown'}),/Unknown quarterback/);
  modern.get('eval-period').value='holdout';modern.get('eval-period').handlers.change();assert.match(modern.get('backtest-summary').textContent,/2026/);
  console.log(JSON.stringify({checks:'projection probabilities, venue, signs, payload integrity, tab isolation, charts, caching',games:data.games.length,maxProbabilityError,maxMarginError}));
})().catch(e=>{console.error(e);process.exitCode=1;});
