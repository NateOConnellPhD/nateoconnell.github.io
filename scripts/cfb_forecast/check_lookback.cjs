/* Offline controller checks. No browser, network, model, or generated fixtures. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const api=require('../../assets/js/cfb-lookback.js');
const edition=(saved_at,kind='saved')=>({kind,saved_at,observed_at:'2026-11-15T00:00:00Z'});
const report={schema:'cfb-lookback-v1',season:2026,results_checked_at:'2026-11-24T00:00:00Z',editions:{
  early:edition('2026-11-20T00:00:00Z'),latest:edition('2026-11-21T00:00:00Z'),late:edition('2026-11-23T00:00:00Z'),
  legacy:edition(null),replay:edition(null,'earlier')},games:[]};
const points={mean:28,median:27,lo80:14,hi80:40,lo95:3,hi95:53};
const game={id:1,season:2026,week:12,season_type:'regular',date:'2026-11-21T18:00:00Z',
  home:{id:'1',name:'Home team'},away:{id:'2',name:'Away team'},neutral:false,status:'final',result:{home:28,away:21},
  predictions:[{edition:'late',timing:'after_kickoff',home_margin:7},
    {edition:'early',timing:'pregame',home_margin:10.01},
    {edition:'latest',timing:'pregame',home_margin:10,p_home:.7,margin_lo80:-5,margin_hi80:25,margin_lo95:-20,margin_hi95:40,
      scores:{home:points,away:{...points,mean:18}}},
    {edition:'replay',timing:'reconstruction',home_margin:-1}]};
report.games=[game,{...game,id:2,week:11,result:null,status:'scheduled',predictions:[{edition:'latest',timing:'pregame',home_margin:3}]},
  {...game,id:3,week:12,home:{id:'3',name:'Third team'},predictions:[{edition:'legacy',timing:'unverified',home_margin:7}]},
  {...game,id:4,week:12,result:null,status:'cancelled',predictions:[{edition:'latest',timing:'pregame',home_margin:7}]}];
assert.deepEqual(api.predictions(game,report,'saved').map(p=>p.edition),['latest','early','late']);
const rows=report.games.map(game=>({game,prediction:api.predictions(game,report,'saved')[0]}));
assert.deepEqual(api.summarize(rows,'saved'),{n:1,within:{3:1,7:1,10:1,14:1},winners:1,decided:1});
assert.equal(api.missed(game,game.predictions[1]),3.01);
assert.equal(api.summarize([{game,prediction:game.predictions[1]}],'saved').within[3],0,'Do not round into a success');
assert.equal(api.summarize([{game,prediction:game.predictions[3]}],'earlier').within[7],0);
assert.equal(api.winner(game,{home_margin:0}),null);
assert.equal(api.winner(game,{home_margin:1,p_home:.49}),false,'Use the saved probability when grading winners');

class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.handlers={};this.dataset={};this.attrs={};this.hidden=false;this.textContent='';this.value='';}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;if(this.tag==='select')this.value=nodes[0]?.attrs.value??'';}
  setAttribute(k,v){this.attrs[k]=String(v);}
  addEventListener(k,fn){(this.handlers[k]??=[]).push(fn);}
  async emit(k){await Promise.all((this.handlers[k]||[]).map(fn=>fn()));}
  focus(){}scrollIntoView(){}
}
const text=e=>e.textContent+e.children?.map(text).join('');
async function controller(){
  const template=fs.readFileSync(path.resolve(__dirname,'../../_includes/cfb-projections.html'),'utf8'),nodes=new Map();
  for(const [,tag,attrs] of template.matchAll(/<([a-z][\w-]*)\b([^>]*)>/g))for(const [,key] of attrs.matchAll(/\bdata-lookback-([\w-]+)(?=[\s=>]|$)/g)){
    const e=new Element(tag);e.hidden=/\bhidden\b/.test(attrs);nodes.set(key,e);
  }
  const get=k=>nodes.get(k)||null,root=new Element(),coverage=new Element('select'),events=new Map(),requests=[];
  root.dataset.index='/assets/data/cfb/projections/lookback-index.json';root.querySelector=s=>get(s.match(/data-lookback-([^\]]+)/)[1]);coverage.value='80';
  const historical={...report,season:2025,games:[{...game,id:5,season:2025,predictions:[game.predictions[3]]}]};
  const fixtures={'lookback-index.json':{schema:'cfb-lookback-v1',seasons:[{season:2026,file:'lookback-2026.json'},{season:2025,file:'lookback-2025.json'}]},
    'lookback-2026.json':report,'lookback-2025.json':historical};
  const doc={querySelector:s=>s==='[data-cfb-lookback]'?root:coverage,createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),
    createTextNode:t=>({textContent:t,children:[]}),addEventListener:(k,f)=>events.set(k,f)};
  const context={document:doc,location:{href:'https://example.test/blog/cfb/'},URL,AbortController,setTimeout,clearTimeout,
    fetch:async url=>{const file=path.basename(String(url));requests.push(file);return{ok:true,json:async()=>fixtures[file]};}};
  context.window=context;
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname,'../../assets/js/cfb-lookback.js'),'utf8'),context);
  return {get,coverage,events,requests,fixtures};
}
(async()=>{
  const c=await controller();assert.equal(c.requests.length,0,'Other tabs must not download lookback');
  await c.events.get('cfb:lookback-activate')();
  assert.deepEqual(c.requests,['lookback-index.json','lookback-2026.json']);
  assert.equal(c.get('season').value,'2026');assert.equal(c.get('source').value,'saved');
  assert.equal(c.get('week').value,'regular:12');assert.equal(c.get('body').hidden,false);assert.equal(c.get('status').textContent,'');
  assert.equal(c.get('within-3').textContent,'100.0%');assert.match(c.get('summary-note').textContent,/1 verified pregame/);
  const body=()=>c.get('games').children[0].children[1];
  const open=()=>body().children[0].children[1].children[0].children[0].emit('click');
  assert.equal(body().children.length,3);
  await open();assert.equal(c.get('detail').hidden,false);assert.equal(c.get('edition').value,'latest');
  assert.match(text(c.get('comparison')),/Correct|Home team by 10.0/);
  assert.equal(c.get('points').hidden,false);assert.match(text(c.get('points')),/80% score range/);
  const previous=JSON.stringify(c.get('range').children[0].attrs);
  c.coverage.value='95';await c.coverage.emit('change');
  assert.match(text(c.get('points')),/95% score range/);assert.notEqual(JSON.stringify(c.get('range').children[0].attrs),previous);
  c.get('edition').value='early';await c.get('edition').emit('change');assert.equal(c.get('edition').value,'early');
  assert.match(text(c.get('comparison')),/10.0/);assert.equal(c.get('points').hidden,true);
  c.get('edition').value='late';await c.get('edition').emit('change');assert.match(c.get('detail-note').textContent,/Created after kickoff/);
  c.get('team').value='3';await c.get('team').emit('change');assert.equal(body().children.length,1);
  assert.equal(c.get('detail').hidden,true);assert.equal(c.get('within-3').textContent,'—');
  c.get('source').value='earlier';await c.get('source').emit('change');await open();
  assert.equal(c.get('team').value,'');assert.match(c.get('context').textContent,/reconstructions/);
  assert.match(text(c.get('range')),/not available/);assert.equal(c.get('points').hidden,true);
  assert.equal(c.requests.length,2,'Filters and intervals reuse saved data');
  c.get('season').value='2025';await c.get('season').emit('change');
  assert.equal(c.get('source').value,'earlier');assert.equal(c.requests.length,3);
  c.get('season').value='2026';await c.get('season').emit('change');assert.equal(c.requests.length,3);
  c.get('week').value='regular:11';await c.get('week').emit('change');assert.match(text(c.get('games')),/Awaiting final/);
  assert.equal(c.get('within-3').textContent,'—');
  const reloading=c.events.get('cfb:lookback-reload')();
  c.coverage.value='80';await c.coverage.emit('change');await reloading;
  assert.equal(c.get('status').textContent,'');assert.equal(c.get('body').hidden,false);
  assert.equal(c.requests.length,5,'Reload must fetch fresh index and selected season');
  console.log('Lookback: provenance, pregame edition selection, unrounded accuracy, season/week/team filters, score details, 80/95 ranges, and lazy caching passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
