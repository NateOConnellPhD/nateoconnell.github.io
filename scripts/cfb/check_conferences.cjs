// Offline component behavior with a minimal DOM; not a rendered browser review.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.handlers={};this.attributes={};this._value='';this.textContent='';}
  set value(v){this._value=String(v);} get value(){return this._value;}
  setAttribute(k,v){this.attributes[k]=v;if(k==='value')this.value=v;}
  append(...n){this.children.push(...n);}
  replaceChildren(...n){this.children=n;if(this.tag==='select')this.value=n[0]?.value||'';}
  addEventListener(k,h){this.handlers[k]=h;}
}
const elements=new Map(),get=k=>{if(!elements.has(k))elements.set(k,new Element(['a','b','metric'].includes(k)?'select':'div'));return elements.get(k);};
const node=(tag,text,attrs={})=>{const n=new Element(tag);n.textContent=text;for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n;};
const context={window:{}};
vm.runInNewContext(fs.readFileSync(require.resolve('../../assets/js/cfb-conferences.js'),'utf8'),context);
const charts=[];
const controller=context.window.CFBConferences({querySelector:s=>get(s.match(/data-cfb-conf-([^\]]+)/)[1])},
  {node,svg:(tag,attrs,text)=>node(tag,text,attrs),num:x=>x.toFixed(2),interval:(a,b)=>`${a.toFixed(2)} to ${b.toFixed(2)}`,
   chart:(target,label)=>{charts.push(label);const plot=new Element('svg');target.replaceChildren(plot);return {plot,x:v=>v,y:v=>v,top:0,bottom:300};}});
const summary=(mean)=>({mean,median:mean,n:4,q05:mean-1,q95:mean+1,distribution:{kind:'histogram',edges:[mean-2,mean,mean+2],counts:[2,2]}});
const rows=[{name:'Big Ten',team_ids:[2],teams:1,teams_with_games:1},{name:'SEC',team_ids:[1],teams:1,teams_with_games:1}];
for(const [i,r] of rows.entries())r.metrics={roster:{point_rank:2-i,strength:summary(i*3),rank:summary(2-i),p_best:i},baseline:{point_rank:i+1,strength:summary(-i*2),rank:summary(i+1),p_best:1-i}};
const data={schema:'margin-of-merit-conferences-v1',conferences:rows,independent_team_ids:[3],comparisons:{}};
for(const [key,gap] of [['roster',3],['baseline',-2]])data.comparisons[key]={'SEC':{'Big Ten':{difference:summary(gap),p_greater:gap>0?1:0,p_equal:0}},'Big Ten':{'SEC':{difference:summary(-gap),p_greater:gap>0?0:1,p_equal:0}}};
const snapshot={season:2026,week:12,reference_rank:12,posterior:{conferences:data},teams:[{id:1,name:'Alabama'},{id:2,name:'Ohio State'},{id:3,name:'Independent School'}]};
const content=n=>[n.textContent||'',...n.children.map(content)].join(' ');
get('metric').value='roster';controller.show(snapshot);controller.tab('conferences');
assert.equal(get('a').value,'SEC');assert.equal(get('b').value,'Big Ten');
assert.match(content(get('pair')),/Estimated gap: 3.00 points/);
assert.match(content(get('pair')),/P\(SEC stronger\) = 100.0%/);
assert.equal(get('rows').children[0].children[1].children[0].textContent,'SEC');
assert.match(charts.at(-1),/SEC minus Big Ten/);
assert.match(get('coverage').textContent,/Independent School/);
assert.match(content(get('members')),/Alabama/);
get('metric').value='baseline';get('metric').handlers.change();
assert.equal(get('rows').children[0].children[1].children[0].textContent,'Big Ten');
assert.match(content(get('pair')),/Estimated gap: -2.00 points/);
get('a').value='Big Ten';get('a').handlers.change();
assert.equal(get('b').value,'SEC');assert.match(content(get('pair')),/Estimated gap: 2.00 points/);
controller.show({...snapshot,reference_rank:2});
assert.equal(get('a').value,'Big Ten');assert.equal(get('metric').value,'baseline');
assert.match(content(get('pair')),/Estimated gap: 2.00 points/);
controller.show({...snapshot,season:2025,posterior:{}});
assert.equal(get('content').hidden,true);assert.equal(get('rows').children.length,0);assert.equal(get('pair').children.length,0);
assert.match(get('status').textContent,/not been saved/);
controller.show(snapshot);controller.tab('rankings');const count=charts.length;controller.resize();assert.equal(charts.length,count,'Hidden conference plots do not redraw');
// Season without the default pair and a single conference: no stale comparison.
const one=JSON.parse(JSON.stringify(snapshot));one.season=2024;one.posterior.conferences.conferences=one.posterior.conferences.conferences.slice(0,1);
controller.show(one);controller.tab('conferences');
assert.equal(get('a').value,'Big Ten');assert.equal(get('b').disabled,true);assert.match(content(get('pair')),/only one/);
assert.equal(get('plot').children.length,0);assert.equal(get('plot-note').textContent,'');
console.log('Conference component checks passed: default pair, both measures, reversed gap, season/reference switches and missing-data states.');
