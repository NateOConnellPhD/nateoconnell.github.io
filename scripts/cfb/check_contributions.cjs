// Offline data/render checks; no browser, network, or generated files.
const assert = require('node:assert/strict');
const {compare, render} = require('../../assets/js/cfb-contributions.js');
const credit = value => ({mean: value, median: value, q05: value, q95: value});
const games = [[1,2,.8,-.3], [1,3,.6,-.4], [2,3,.4,-.6], [1,9,.2,-.8],
  [9,2,.8,-.8], [2,3,.3,-.7], [4,1,.7,-.5], [2,5,.9,-.1]].map(([home,away,h,a],i) => ({
  id: 100+i, week: i, start_date: `2026-09-${String(i+1).padStart(2,'0')}T18:00:00Z`,
  home_id: home, away_id: away, home_points: 21, away_points: 14, neutral_site: i===0,
  home_credit: credit(h), away_credit: credit(a)}));
const teams = [1,2,3,4,5].map((id,i) => ({id, name: `Team ${id}`, rank: i+1, ...(() => {
  const rows = games.filter(g => g.home_id===id || g.away_id===id);
  return {wins:rows.filter(g=>g.home_id===id).length, losses:rows.filter(g=>g.away_id===id).length,
    merit_mean:rows.reduce((sum,g)=>sum+g[g.home_id===id?'home_credit':'away_credit'].mean,0)};
})()}));
const snapshot = {reference_rank:12, teams, policy_inputs:{games:structuredClone(games), opponents:[{id:9,name:'FCS Team'}]},
  game_contributions:{schema:'margin-of-merit-game-contributions-v1', reference_rank:12, games}};
const result = compare(snapshot,1,2);
assert.deepEqual(result.groups.map(g=>g.games.map(rows=>rows.length)), [[1,1],[2,3],[1,1]]);
assert.deepEqual([...result.common].sort(), [3,9], 'Common FCS opponents are part of merit attribution');
assert.ok(Math.abs(result.gap-.6)<1e-12);
for (const [i,value] of [1.1,.9,-1.4].entries()) assert.ok(Math.abs(result.groups[i].gap-value)<1e-12);
assert.ok(Math.abs(result.groups.reduce((sum,g)=>sum+g.gap,0)-result.gap)<1e-12);
for (const i of [0,1]) {
  const ids=result.groups.flatMap(g=>g.games[i]).map(g=>g.game);
  assert.equal(new Set(ids).size,ids.length,'No game counted twice for one team');
}
assert.equal(result.groups[0].games[0][0].venue,'Neutral');
assert.equal(result.groups[2].games[0][0].venue,'Away');
assert.equal(result.groups[2].games[0][0].result,'L 14–21');
const reversed=compare(snapshot,2,1);
assert.equal(reversed.gap,-result.gap);
result.groups.forEach((g,i)=>assert.equal(reversed.groups[i].gap,-g.gap));
assert.equal(compare({...snapshot,game_contributions:undefined},1,2),null);
assert.throws(()=>compare({...snapshot,reference_rank:4},1,2),/reference/);
const corrupt=structuredClone(snapshot); corrupt.game_contributions.games[0].home_credit.mean+=.01;
assert.throws(()=>compare(corrupt,1,2),/reconcile/);
const missing=structuredClone(snapshot); missing.game_contributions.games.pop();
assert.throws(()=>compare(missing,1,2),/schedule/);
const duplicate=structuredClone(snapshot); duplicate.game_contributions.games[0]=duplicate.game_contributions.games[1];
assert.throws(()=>compare(duplicate,1,2),/schedule/);
const idle={...snapshot,teams:snapshot.teams.map(t=>({...t,rank:null}))};
assert.throws(()=>compare(idle,1,2),/ranked/);
const noDirect=compare(snapshot,1,5);
assert.equal(noDirect.groups[0].games[0].length,0);
assert.equal(noDirect.groups[0].games[1].length,0);

class Element {
  constructor(tag,doc) {this.tag=tag; this.ownerDocument=doc; this.children=[]; this.textContent=''; this.attrs={};}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children=children;}
  setAttribute(k,v) {this.attrs[k]=v;}
}
const doc={createElement(tag){return new Element(tag,doc);}};
const container=new Element('div',doc);
const text=n=>[n.textContent,...n.children.map(text)].join(' ');
const all=n=>[n,...n.children.flatMap(all)];
render(container,snapshot,1,2,teams.map(t=>({...t,rank:t.id===1?2:1})));
assert.match(text(container),/Team 1 has 0.600 more merit than Team 2/);
assert.match(text(container),/team with less mean merit is ranked higher/);
assert.match(text(container),/FCS Team \(FCS\)/);
assert.match(text(container),/Credit against each common opponent \(all meetings\)/);
assert.match(text(container),/interval endpoints do not add/);
assert.equal(all(container).filter(n=>n.tag==='details').length,3);
assert.equal(all(container).filter(n=>n.tag==='details' && n.open).length,1,'Only the direct games start expanded');
assert.ok(all(container).filter(n=>n.attrs.role==='region').every(n=>n.tabIndex===0),'Tables remain keyboard-scrollable');
render(container,{...snapshot,game_contributions:undefined},1,2,teams);
assert.match(text(container),/does not yet include game-by-game credit/);
assert.doesNotMatch(text(container),/0.600|FCS Team/,'Switching to an older snapshot removes previous games');
render(container,corrupt,1,2,teams);
assert.match(text(container),/could not be reconciled/);
assert.equal(all(container).filter(n=>n.tag==='table').length,0,'Never display an unreconciled breakdown');
console.log('Game contribution grouping, reconciliation, reversed pairs and offline rendering checks passed.');
