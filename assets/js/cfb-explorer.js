/* Static empirical posterior and season-history explorer. No inference or APIs. */
window.CFBExplorer = (root, api) => {
  'use strict';
  const el = name => root.querySelector(`[data-cfb-${name}]`);
  const colors = ['#245a82', '#778599'];
  const seriesCache = new Map();
  let current, archive, series, historySequence = 0, activeTab = 'rankings';
  const metrics = {
    merit: ['Earned merit', 'Total credit from the games a team has played, accounting for opponents, margins, and venue. Wins add credit; losses subtract it. Higher is better.'],
    raw_rank: ['Raw merit rank', 'Where the team falls by earned merit in each sampled scenario, before the additional ranking rules. Tied teams share their positions. Lower is better.'],
    strength: ['Team strength (points)', 'Estimated underlying strength in points, using all eligible games. Differences between teams describe expected scoring margins, rather than the merit they have earned.'],
    sos: ['Strength of schedule (loss probability)', 'Average probability that the reference team—the 25th-strongest team in each draw—would lose against this schedule, accounting for venue. The scale is 0 to 1: 0.30 means 30%. Higher means a harder schedule. Each game is left out when estimating its difficulty.'],
    home_adv: ['Home advantage (points)', 'The common point advantage associated with playing at home. Neutral-site games receive no home advantage.'],
    sigma: ['Residual scale (points)', 'How widely scores vary around the margins suggested by team strengths and venue. This scale has an eight-point minimum and is not literally a standard deviation.'],
    nu: ['Degrees of freedom', 'How readily the model allows unusually extreme scores. Smaller values allow more surprising blowouts.']
  };
  const num = x => Number.isFinite(x) ? x.toFixed(2) : '—';
  const interval = (a,b) => `${num(a)} to ${num(b)}`;
  function node(tag, text, attrs = {}) {
    const n = document.createElement(tag); if (text != null) n.textContent = text;
    for (const [k,v] of Object.entries(attrs)) n.setAttribute(k,v); return n;
  }
  function svg(tag, attrs = {}, text) {
    const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k,v] of Object.entries(attrs)) n.setAttribute(k,v);
    if (text != null) n.textContent = text; return n;
  }
  function chart(target, label, xmin, xmax, ymin, ymax, reverse = false, integerX = false) {
    const width = Math.max(300, Math.min(1000, target.clientWidth || 700)), height = 310;
    const left = 57, right = width - 18, top = 22, bottom = height - 47;
    if (xmax === xmin) { xmin -= .5; xmax += .5; }
    if (ymax === ymin) { ymin -= .5; ymax += .5; }
    const x = v => left + (v-xmin)/(xmax-xmin)*(right-left);
    const y = v => reverse ? top+(v-ymin)/(ymax-ymin)*(bottom-top) : bottom-(v-ymin)/(ymax-ymin)*(bottom-top);
    const plot = svg('svg', {viewBox:`0 0 ${width} ${height}`, role:'img', 'aria-label':label});
    plot.append(svg('title', {}, label));
    for (let i=0;i<=4;i++) {
      const value = ymin+(ymax-ymin)*i/4, yy = y(value);
      plot.append(svg('line', {x1:left,x2:right,y1:yy,y2:yy,stroke:'#bfd2e1'}));
      plot.append(svg('text', {x:left-8,y:yy+4,'text-anchor':'end'}, Math.abs(value)<.01 && value!==0 ? value.toExponential(1) : value.toFixed(Math.abs(ymax-ymin)<3?2:0)));
    }
    const ticks = integerX ? Array.from({length:Math.floor(xmax)-Math.ceil(xmin)+1}, (_,i)=>Math.ceil(xmin)+i)
      .filter((v,i)=>i%Math.max(1,Math.ceil((xmax-xmin)/6))===0 || v===xmax)
      : Array.from({length:5},(_,i)=>xmin+(xmax-xmin)*i/4);
    for (const v of ticks) plot.append(svg('text', {x:x(v),y:bottom+23,'text-anchor':'middle'}, integerX?`W${v}`:v.toFixed(2)));
    target.replaceChildren(plot);
    return {plot,x,y,top,bottom,left,right};
  }
  function legend(target, entries, suffix) {
    target.replaceChildren(...entries.map((entry,i) => {
      const item = node('span', entry.name); item.style.borderColor = colors[i]; return item;
    }));
    if (suffix) target.append(node('small', suffix));
  }
  function summaryRow(name, s) {
    const tr = node('tr');
    for (const value of [name, num(s.mean), num(s.median), num(s.sd), interval(s.q25,s.q75), interval(s.q05,s.q95), s.n]) tr.append(node('td',value));
    return tr;
  }
  function renderPosterior() {
    if (!current || activeTab !== 'posterior') return;
    const key = el('metric').value, global = ['home_adv','sigma','nu'].includes(key);
    const ids = [el('stat-team').value, el('stat-other').value].filter((v,i,a)=>v && a.indexOf(v)===i);
    el('stat-team').disabled = global; el('stat-other').disabled = global;
    el('stat-context').textContent = metrics[key][1];
    const entries = global ? [{name:metrics[key][0], s:current.posterior?.parameters?.[key]}]
      : ids.map(id=>({name:current.teams.find(t=>String(t.id)===id)?.name, s:current.posterior?.teams?.[id]?.[key]}));
    el('stat-summary').replaceChildren(); el('stat-legend').replaceChildren(); el('probabilities').replaceChildren();
    el('distribution').replaceChildren(); el('stat-note').textContent = '';
    if (entries.some(e=>!e.s)) {
      el('distribution').append(node('p', current.posterior
        ? 'This quantity is unavailable for a selected team without eligible games. Choose team strength to inspect its posterior.'
        : 'This older snapshot did not retain distributions or medians. Choose a newly generated update; intervals alone cannot recover a posterior distribution.'));
      return;
    }
    const cdf = el('chart-mode').value === 'cdf';
    const mass = entries.every(e=>e.s.distribution.kind==='mass');
    const points = entries.flatMap(e=>e.s.distribution.edges || e.s.distribution.x);
    let maxY = 0;
    entries.forEach(e=> {
      const h=e.s.distribution;
      e.heights=h.counts.map((count,i)=>count/e.s.n/(h.kind==='histogram'&&!cdf ? h.edges[i+1]-h.edges[i] : 1));
      if (mass || h.kind==='histogram' || cdf) maxY=Math.max(maxY,...e.heights);
    });
    const unit=cdf?'Cumulative probability':mass?'Probability mass':'Density';
    const {plot,x,y,top,bottom}=chart(el('distribution'), `${metrics[key][0]}: ${unit}. Exact summary statistics in the table below.`, Math.min(...points),Math.max(...points),0,cdf?1:maxY*1.12);
    plot.append(svg('text',{x:57,y:14},unit));
    entries.forEach((entry,j)=> {
      const s=entry.s, h=s.distribution, color=colors[j];
      let cumulative=0, path='';
      h.counts.forEach((count,i)=> {
        const low=h.kind==='histogram'?h.edges[i]:h.x[i];
        const high=h.kind==='histogram'?h.edges[i+1]:low;
        if (cdf) {
          if (!i) path=`M${x(low)},${y(0)}`;
          if (h.kind==='histogram') {
            cumulative+=count/s.n; path+=` L${x(high)},${y(cumulative)}`;
          } else {
            path+=` L${x(low)},${y(cumulative)}`; cumulative+=count/s.n; path+=` L${x(low)},${y(cumulative)}`;
          }
        } else if (mass || h.kind==='histogram') {
          const bar=h.kind==='histogram' ? svg('rect',{x:x(low),y:y(entry.heights[i]),width:Math.max(.1,x(high)-x(low)),height:bottom-y(entry.heights[i]),fill:color,opacity:.28})
            : svg('line',{x1:x(low),x2:x(low),y1:bottom,y2:y(entry.heights[i]),stroke:color,'stroke-width':j?2:5,opacity:.8});
          bar.append(svg('title',{},`${entry.name}: ${num(low)}${high!==low?' to '+num(high):''}; ${(count/s.n*100).toFixed(2)}% (${count} draws)`)); plot.append(bar);
        }
      });
      if (cdf) plot.append(svg('path',{d:path,fill:'none',stroke:color,'stroke-width':2.5,'stroke-dasharray':j?'6 3':''}));
      for (const [field,dash] of [['mean',''],['median','4 4']]) {
        const line=svg('line',{x1:x(s[field]),x2:x(s[field]),y1:top,y2:bottom,stroke:color,'stroke-width':1.5,'stroke-dasharray':dash});
        line.append(svg('title',{},`${entry.name} ${field}: ${num(s[field])}`)); plot.append(line);
      }
      el('stat-summary').append(summaryRow(entry.name,s));
    });
    legend(el('stat-legend'),entries,'Vertical lines: solid = mean; dashed = median.');
    if (!mass && !cdf) for (const entry of entries.filter(e=>e.s.distribution.kind==='mass')) {
      el('stat-legend').append(node('small',`${entry.name} is a point mass at ${num(entry.s.mean)} (100% of draws), shown by its vertical summary line; it has no continuous density.`));
    }
    el('stat-note').textContent = `${global || key === 'strength'
      ? 'These estimates use the model fitted to all eligible games through this cutoff.'
      : 'These estimates combine leave-one-game-out calculations, so a game does not help grade itself. Their joint uncertainty is approximate.'} Summary statistics use all retained draws. Intervals contain the middle 50% or 90% of those draws. ${cdf&&!mass?'The continuous cumulative curve is approximated between saved bin boundaries.':'The plot groups continuous draws into bins; separate rank values show their share of the draws.'}`;
    if (!global) {
      for (const id of ids) {
        const team=current.teams.find(t=>String(t.id)===id), box=node('p');
        box.append(node('strong',team.name));
        box.append(document.createTextNode(' · '+[8,10,25].map(k=>`P(raw top ${k}) = ${Number.isFinite(team[`p_raw_merit_top${k}`])?(100*team[`p_raw_merit_top${k}`]).toFixed(1)+'%':'unavailable'}`).join(' · ')));
        el('probabilities').append(box);
      }
      if (ids.length===2 && current.policy_inputs) {
        const order=current.policy_inputs.teams.map(t=>String(t.id));
        const p=current.policy_inputs.probabilities[order.indexOf(ids[0])][order.indexOf(ids[1])];
        el('probabilities').append(node('p',`P(${entries[0].name} has higher earned merit than ${entries[1].name}) = ${(p*100).toFixed(2)}%. This uses strictly greater merit. This is not a game-win probability.`));
      }
    }
  }
  function renderHistory() {
    if (!current || activeTab !== 'history' || !series) return;
    const key=el('history-metric').value, ids=[el('history-team').value,el('history-other').value].filter((v,i,a)=>v&&a.indexOf(v)===i);
    const published=new Set(archive.snapshots.map(r=>r.id));
    const weeks=series.weeks.filter(w=>published.has(w.id)), field=key==='rank'?'rank':`${key}_mean`;
    const entries=ids.map(id=>({name:current.teams.find(t=>String(t.id)===id)?.name, points:weeks.map(w=>({week:w.week,policy:w.policy_sha256,t:w.teams.find(t=>String(t.id)===id),id:w.id}))}));
    const finite=entries.flatMap(e=>e.points.filter(p=>Number.isFinite(p.t?.[field])));
    el('trajectory').replaceChildren(); el('history-rows').replaceChildren();
    el('history-caption').textContent=`${current.season} weekly history · official saved results`;
    el('history-status').textContent=`${weeks.length} saved week${weeks.length===1?'':'s'} in ${current.season}. ${weeks.length<2?'A trajectory needs at least two saved weeks. ':''}Weeks awaiting refits break the line. Rule sliders do not alter this history.`;
    if (!finite.length) { el('trajectory').append(node('p','No eligible-game summaries for these teams in the saved weeks.')); return; }
    const lows=finite.map(p=>key==='rank'?p.t.rank:p.t[`${key}_lo90`]);
    const highs=finite.map(p=>key==='rank'?p.t.rank:p.t[`${key}_hi90`]);
    const coverage=archive.archive?.find(s=>s.season===current.season)?.weeks.map(w=>w.week)||[];
    const xmin=Math.min(...weeks.map(w=>w.week),...coverage),xmax=Math.max(...weeks.map(w=>w.week),...coverage);
    const {plot,x,y}=chart(el('trajectory'),`${current.season}: ${key==='rank'?'official ranks':key+' means with 90% intervals'} by week`,xmin,xmax,Math.min(...lows),Math.max(...highs),key!=='merit',true);
    entries.forEach((entry,j)=> {
      let prior=null;
      for (const point of entry.points) {
        const t=point.t;
        if (!Number.isFinite(t?.[field])) { prior=null; continue; }
        if (prior && point.week===prior.week+1 && (key!=='rank'||point.policy===prior.policy)) {
          plot.append(svg('line',{x1:x(prior.week),x2:x(point.week),y1:y(prior.t[field]),y2:y(t[field]),stroke:colors[j],'stroke-width':2,'stroke-dasharray':j?'6 3':''}));
        }
        if (key!=='rank') plot.append(svg('line',{x1:x(point.week),x2:x(point.week),y1:y(t[`${key}_lo90`]),y2:y(t[`${key}_hi90`]),stroke:colors[j],'stroke-width':6,opacity:.25}));
        const dot=svg('circle',{cx:x(point.week),cy:y(t[field]),r:4,fill:colors[j]});
        dot.append(svg('title',{},`${entry.name}, week ${point.week}: ${num(t[field])}`)); plot.append(dot);
        prior=point;
      }
    });
    const previous=new Map();
    for (const w of weeks) for (const id of ids) {
      const t=w.teams.find(t=>String(t.id)===id); if (!t) continue;
      const prior=previous.get(id), comparable=prior&&prior.week===w.week-1&&prior.policy===w.policy_sha256;
      const change=comparable&&Number.isFinite(prior.rank)&&Number.isFinite(t.rank)?prior.rank-t.rank:null;
      const movement=!comparable?'N/A':!Number.isFinite(t.rank)?'Unranked':!Number.isFinite(prior.rank)?'New':change>0?`↑ ${change}`:change<0?`↓ ${-change}`:'0 (unchanged)';
      const tr=node('tr'), td=node('td'), link=node('button',`Week ${w.week}`,{type:'button',class:'cfb-inline-button'});
      link.addEventListener('click',()=>api.select(w.id)); td.append(link); tr.append(td);
      for (const value of [t.name,t.rank??'—',`${t.wins}–${t.losses}`,`${num(t.merit_mean)} / ${num(t.merit_median)}`,interval(t.merit_lo90,t.merit_hi90),movement]) tr.append(node('td',value));
      el('history-rows').append(tr); previous.set(id,{week:w.week,rank:t.rank,policy:w.policy_sha256});
    }
    legend(el('history-legend'),entries,key==='rank'?'Official point ranks; no posterior interval is assigned to these rule-adjusted ranks.':'Points = posterior means; bars = equal-tailed 90% intervals.');
  }
  async function loadHistory() {
    if (!current || activeTab!=='history') return;
    const season=current.season, sequence=++historySequence;
    el('history-status').textContent='Loading saved season history…';
    series=null; el('trajectory').replaceChildren(); el('history-rows').replaceChildren(); el('history-legend').replaceChildren();
    try {
      if (!seriesCache.has(season)) {
        const data=await api.fetchJSON(api.url(`seasons/${season}/history.json`));
        if (data.schema!=='margin-of-merit-history-v1'||data.season!==season||!Array.isArray(data.weeks)) throw new Error('Invalid history');
        seriesCache.set(season,data);
      }
      if (sequence!==historySequence||current.season!==season) return;
      series=seriesCache.get(season); renderHistory();
    } catch (_) { if(sequence===historySequence) el('history-status').textContent='The season history is not available yet. Saved updates remain accessible in the archive above.'; }
  }
  function tab(name, focus=false) {
    activeTab=name;
    root.querySelectorAll('[data-cfb-tab]').forEach(b=>{const chosen=b.dataset.cfbTab===name;b.setAttribute('aria-selected',chosen);b.tabIndex=chosen?0:-1;if(chosen&&focus)b.focus();});
    root.querySelectorAll('[data-cfb-panel]').forEach(p=>p.hidden=p.dataset.cfbPanel!==name);
    if(name==='posterior') renderPosterior(); if(name==='history') loadHistory();
  }
  root.querySelectorAll('[data-cfb-tab]').forEach((b,i,buttons)=> {
    b.addEventListener('click',()=>tab(b.dataset.cfbTab));
    b.addEventListener('keydown',e=>{const keys=['ArrowRight','ArrowLeft','Home','End'];if(!keys.includes(e.key))return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;tab(buttons[n].dataset.cfbTab,true);});
  });
  for(const key of ['stat-team','stat-other','metric','chart-mode']) el(key).addEventListener('change',renderPosterior);
  for(const key of ['history-team','history-other','history-metric']) el(key).addEventListener('change',renderHistory);
  let resizeFrame;
  new ResizeObserver(()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(()=>{renderPosterior();renderHistory();});}).observe(root);
  return {
    tab,
    show(value, index) {
      current=value; archive=index; historySequence++;
      const teams=[...current.teams].sort((a,b)=>a.name.localeCompare(b.name));
      for(const key of ['stat-team','stat-other','history-team','history-other']) {
        const control=el(key), old=control.value, optional=key.endsWith('other');
        control.replaceChildren(...(optional?[node('option','None',{value:''})]:[]),...teams.map(t=>node('option',t.name,{value:t.id})));
        control.value=teams.some(t=>String(t.id)===old)?old:optional?'':String(current.order[0]);
      }
      const d=current.sampling_diagnostics,l=current.loo_diagnostics;
      el('diagnostics').replaceChildren(node('p',d?`Maximum rank-normalized R̂: ${num(d.max_rank_normalized_rhat)}. Minimum bulk ESS: ${num(d.min_bulk_ess)}; tail ESS: ${num(d.min_tail_ess)}. Divergences: ${d.divergences}; tree-depth limit hits: ${d.tree_depth_limit_hits}.`:'Diagnostics not retained in this snapshot.'),node('p',l?`PSIS flagged ${l.psis_unreliable_games??'—'} games; ${l.exact_refits??'—'} exact omitted-game refits. Remaining unreliable games: ${l.unreliable_games}. Maximum transport mean error: ${l.max_transport_mean_error??'—'}.`:''));
      if(activeTab==='posterior') renderPosterior(); if(activeTab==='history') loadHistory();
    },
    team(id) {el('stat-team').value=String(id);el('stat-other').value='';tab('posterior',true);el('metric').focus();}
  };
};
