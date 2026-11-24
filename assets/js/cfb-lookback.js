/* Frozen forecasts against saved results. Never predict a past game with today's fit. */
(function(host,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else {host.CFBLookback=api;api.mount(document);}
})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  function predictions(game,report,kind) {
    const priority={pregame:0,unverified:1,reconstruction:2,after_kickoff:3};
    return game.predictions.filter(p=>report.editions[p.edition].kind===kind).sort((a,b)=>{
      const x=report.editions[a.edition],y=report.editions[b.edition];
      return priority[a.timing]-priority[b.timing]
        || String(y.saved_at||y.observed_at||'').localeCompare(String(x.saved_at||x.observed_at||''))
        || a.edition.localeCompare(b.edition);
    });
  }
  const missed=(g,p)=>g.result?Math.abs(p.home_margin-(g.result.home-g.result.away)):null;
  function winner(g,p) {
    if(!g.result)return null;
    const direction=Number.isFinite(p.p_home)?Math.sign(p.p_home-.5):Math.sign(p.home_margin);
    return direction===0?null:direction===Math.sign(g.result.home-g.result.away);
  }
  function summarize(rows,kind) {
    const scored=rows.filter(({game,prediction})=>game.result&&(kind==='earlier'||prediction.timing==='pregame'));
    const decided=scored.filter(({game,prediction})=>winner(game,prediction)!==null);
    return {n:scored.length,within:Object.fromEntries([3,7,10,14].map(k=>[k,scored.filter(({game,prediction})=>missed(game,prediction)<=k).length])),
      winners:decided.filter(({game,prediction})=>winner(game,prediction)).length,decided:decided.length};
  }
  function mount(doc) {
    const root=doc.querySelector('[data-cfb-lookback]');if(!root)return;
    const el=k=>root.querySelector(`[data-lookback-${k}]`);
    const coverageControl=doc.querySelector('[data-projection-coverage]');
    const level=()=>coverageControl.value==='95'?95:80;
    const node=(tag,text,attrs={})=>{const n=doc.createElement(tag);if(text!=null)n.textContent=text;for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
    const date=v=>new Date(v).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric',timeZone:'America/New_York'});
    const editionDate=v=>new Date(v).toLocaleString(undefined,{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',timeZone:'America/New_York'});
    const fmt=v=>Number.isFinite(v)?v.toFixed(1):'Not saved';
    const percent=(n,d)=>d?`${(100*n/d).toFixed(1)}%`:'—';
    const weekKey=g=>`${g.season_type}:${g.week}`;
    const weekLabel=g=>`${g.season_type==='regular'?'Week':'Postseason week'} ${g.week}`;
    const provenance={pregame:'Saved before kickoff',unverified:'Save time not recorded',reconstruction:'Retrospective estimate',after_kickoff:'Created after kickoff'};
    const margin=(g,m)=>Math.abs(m)<.05?'Evenly matched':`${g[m>0?'home':'away'].name} by ${Math.abs(m).toFixed(1)}`;
    const matchup=g=>`${g.away.name} ${g.neutral?'vs.':'at'} ${g.home.name}`;
    const result=g=>g.result?`${g.away.name} ${g.result.away} – ${g.home.name} ${g.result.home}`:
      ({cancelled:'Cancelled',no_contest:'No contest',unverified:'Result needs verification'})[g.status]||'Awaiting final';
    const base=new URL(root.dataset.index,location.href),cache=new Map();
    let index,report,rows=[],selected=null,active=false,turn=0,pending=null,generation=0;
    function table(target,heads,values) {
      const t=node('table'),head=node('thead'),tr=node('tr'),body=node('tbody');
      heads.forEach(h=>tr.append(node('th',h,{scope:'col'})));head.append(tr);
      values.forEach(row=>{const r=node('tr');row.forEach(value=>{const c=node('td');c.append(typeof value==='object'?value:doc.createTextNode(String(value)));r.append(c);});body.append(r);});
      t.append(head,body);target.replaceChildren(t);
    }
    function read(file) {
      if(!/^lookback-(index|\d{4})\.json$/.test(file))return Promise.reject(new Error('Invalid lookback file'));
      if(!cache.has(file)){
        const request=(async()=>{const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),20000);
          try{const response=await fetch(new URL(file,base),{cache:'no-cache',signal:abort.signal});
            if(!response.ok)throw new Error('Lookback could not be loaded. Use Reload to try again.');
            const value=await response.json();if(value.schema!=='cfb-lookback-v1')throw new Error('Unsupported lookback data.');return value;
          }finally{clearTimeout(timer);}})();
        cache.set(file,request);request.catch(()=>cache.delete(file));
      }return cache.get(file);
    }
    async function activate(){
      active=true;if(report)return;
      if(pending)return pending;
      const version=generation;
      pending=(async()=>{try{
        el('status').textContent='Loading past predictions…';
        const loaded=await read('lookback-index.json');if(version!==generation)return;
        index=loaded;
        el('season').replaceChildren(...index.seasons.map(s=>node('option',s.season,{value:String(s.season)})));
        await loadSeason();
      }catch(e){if(version===generation)el('status').textContent=e.message;}finally{if(version===generation)pending=null;}})();
      return pending;
    }
    async function loadSeason(){
      if(!index)return;
      const token=++turn;el('body').hidden=true;el('detail').hidden=true;el('status').textContent='Loading season…';
      try{
        const choice=index.seasons.find(s=>String(s.season)===el('season').value);
        const value=await read(choice.file);if(token!==turn)return;
        report=value;selected=null;
        const kinds=[...new Set(Object.values(report.editions).map(e=>e.kind))];
        el('source').replaceChildren(...['saved','earlier'].filter(k=>kinds.includes(k)).map(k=>node('option',k==='saved'?'Saved forecasts':'Earlier model · reconstructed',{value:k})));
        const verifiedFinal=report.games.some(g=>g.result&&g.predictions.some(p=>p.timing==='pregame'));
        el('source').value=verifiedFinal?'saved':kinds.includes('earlier')?'earlier':'saved';
        resetFilters();el('body').hidden=false;el('status').textContent='';
      }catch(e){if(token===turn)el('status').textContent=e.message;}
    }
    function resetFilters(){
      if(!report)return;
      const kind=el('source').value,games=report.games.filter(g=>predictions(g,report,kind).length);
      const weeks=new Map();games.forEach(g=>weeks.set(weekKey(g),g));
      el('week').replaceChildren(node('option','All weeks',{value:''}),...[...weeks.values()].sort((a,b)=>
        (a.season_type==='postseason')-(b.season_type==='postseason')||a.week-b.week).map(g=>node('option',weekLabel(g),{value:weekKey(g)})));
      const finals=games.filter(g=>g.result),latest=finals[finals.length-1]||games[0];
      el('week').value=latest?weekKey(latest):'';
      const teams=new Map();games.forEach(g=>[g.home,g.away].forEach(t=>teams.set(t.id,t.name)));
      el('team').replaceChildren(node('option','All teams',{value:''}),...[...teams].sort((a,b)=>a[1].localeCompare(b[1])).map(([id,name])=>node('option',name,{value:id})));
      el('team').value='';selected=null;render();
    }
    function render(){
      if(!report)return;
      const kind=el('source').value,week=el('week').value,team=el('team').value;
      rows=report.games.filter(g=>(!week||weekKey(g)===week)&&(!team||g.home.id===team||g.away.id===team))
        .map(game=>({game,prediction:predictions(game,report,kind)[0]})).filter(r=>r.prediction);
      el('context').textContent=kind==='earlier'
        ? 'Earlier power model, before QB and team-score extensions. These weekly reconstructions use earlier game results, but some inputs were collected later. They show a historical evaluation, not forecasts recorded at the time.'
        : 'Original saved predictions, paired with the latest saved final results. The table selects the latest verified pregame forecast for each game when available. Older snapshots without a recorded save time are labeled and excluded from the accuracy totals.';
      if(kind==='earlier'&&Object.values(report.editions).some(e=>e.period==='development'))
        el('context').textContent+=' This season also helped develop the model, so it is not an independent test.';
      const stats=summarize(rows,kind);
      for(const k of [3,7,10,14])el('within-'+k).textContent=percent(stats.within[k],stats.n);
      el('winner').textContent=percent(stats.winners,stats.decided);
      el('summary-note').textContent=`${stats.n} ${kind==='earlier'?'reconstructed':'verified pregame'} predictions with final results in this selection. `+
        (stats.decided?`Winner: ${stats.winners} of ${stats.decided} non-even predictions. `:'')+
        '“Within” compares the predicted score difference with the final score difference, before rounding.';
      const scores=rows.some(r=>r.prediction.scores);
      table(el('games'),['Week','Matchup',...(scores?['Predicted score (mean)']:[]),'Predicted margin','Final score','Margin miss','Winner'],rows.map(({game:g,prediction:p})=>{
        const b=node('button',matchup(g),{type:'button',class:'cfb-forecast-game'});
        b.addEventListener('click',()=>{selected=g.id;renderDetail();el('detail').scrollIntoView({behavior:'smooth',block:'start'});el('detail-title').focus({preventScroll:true});});
        const label=node('div');label.append(b);
        if(kind==='saved')label.append(node('small',provenance[p.timing],{class:'cfb-lookback-provenance'}));
        const points=p.scores?[`${fmt(p.scores.away.mean)} – ${fmt(p.scores.home.mean)}`]:['Not saved'];
        return [weekLabel(g),label,...(scores?points:[]),margin(g,p.home_margin),result(g),g.result?`${fmt(missed(g,p))} pts`:'—',
          !g.result?'—':winner(g,p)===null?'Even prediction':winner(g,p)?'Correct':'Incorrect'];
      }));
      el('count').textContent=`${rows.length} games. Results checked ${date(report.results_checked_at)}. Select a game for its saved forecasts and uncertainty.`;
      if(!rows.some(r=>r.game.id===selected))selected=null;
      renderDetail();
    }
    function renderDetail(keepEdition=false){
      if(!report){el('detail').hidden=true;return;}
      const row=rows.find(r=>r.game.id===selected);el('detail').hidden=!row;if(!row)return;
      const g=row.game,options=predictions(g,report,el('source').value);
      const previous=keepEdition?el('edition').value:null;
      el('edition').replaceChildren(...options.map(p=>{const e=report.editions[p.edition];return node('option',
        `${e.saved_at?editionDate(e.saved_at)+' ET':e.observed_at?'Data observed '+editionDate(e.observed_at)+' ET':'Weekly reconstruction'} · ${provenance[p.timing]}`,
        {value:p.edition});}));
      el('edition').value=options.some(p=>p.edition===previous)?previous:options[0].edition;
      const p=options.find(p=>p.edition===el('edition').value),e=report.editions[p.edition],n=level();
      el('detail-title').textContent=matchup(g);
      el('detail-note').textContent=`${weekLabel(g)} · ${date(g.date)}. ${provenance[p.timing]}. `+
        (p.timing==='pregame'?'This estimate was saved before kickoff.':p.timing==='unverified'?'This snapshot has no recorded creation time, so it cannot establish a pregame prediction.':
          'This is a retrospective estimate and is not included in verified pregame accuracy.')+(e.caveat?' '+e.caveat:'');
      const values=[['Predicted margin',margin(g,p.home_margin)],['Actual result',result(g)],
        ['Margin miss',g.result?`${fmt(missed(g,p))} points`:'Awaiting final']];
      if(Number.isFinite(p.p_home))values.push([`${g.home.name} win probability`,percent(p.p_home,1)],[`${g.away.name} win probability`,percent(1-p.p_home,1)]);
      table(el('comparison'),['Measure','Value'],values);
      el('points').hidden=!p.scores;
      if(p.scores)table(el('points'),['Team','Predicted mean','Median',`${n}% score range`,'Actual'],['away','home'].map(side=>{
        const s=p.scores[side];return [g[side].name,fmt(s.mean),fmt(s.median),`${fmt(s['lo'+n])}–${fmt(s['hi'+n])}`,g.result?g.result[side]:'Awaiting final'];
      }));
      renderRange(g,p,n);
    }
    function renderRange(g,p,n){
      const low=p['margin_lo'+n],high=p['margin_hi'+n];
      if(!Number.isFinite(low)||!Number.isFinite(high)){
        el('range').replaceChildren(node('p','This earlier estimate saved the predicted margin only; score predictions and uncertainty ranges are not available.'));return;
      }
      const actual=g.result?g.result.home-g.result.away:null;
      const lo=Math.min(low,p.home_margin,actual??low,0)-3,hi=Math.max(high,p.home_margin,actual??high,0)+3,x=v=>45+(v-lo)/(hi-lo)*550;
      const svg=(tag,attrs,text)=>{const s=doc.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))s.setAttribute(k,v);if(text)s.textContent=text;return s;};
      const chart=svg('svg',{viewBox:'0 0 640 125',role:'img','aria-label':`${n}% predicted margin range ${fmt(low)} to ${fmt(high)} points. Predicted mean ${fmt(p.home_margin)}.${actual!==null?' Actual margin '+actual+'.':''}`});
      chart.append(svg('line',{x1:x(low),x2:x(high),y1:45,y2:45,stroke:'#7da5c2','stroke-width':12}),
        svg('line',{x1:x(0),x2:x(0),y1:15,y2:70,stroke:'#385369','stroke-dasharray':'3 3'}),
        svg('line',{x1:x(p.home_margin),x2:x(p.home_margin),y1:30,y2:60,stroke:'#142f43','stroke-width':3}));
      if(actual!==null)chart.append(svg('circle',{cx:x(actual),cy:45,r:6,fill:'#aa5b16',stroke:'#fff','stroke-width':2}));
      [lo,(lo+hi)/2,hi].forEach(v=>chart.append(svg('text',{x:x(v),y:92,'text-anchor':'middle'},fmt(v))));
      chart.append(svg('text',{x:320,y:117,'text-anchor':'middle'},`${g.home.name}’s final margin (points)`));
      el('range').replaceChildren(chart,node('p',`Blue bar: ${n}% predicted range. Dark mark: predicted mean. ${actual!==null?'Gold dot: actual margin. ':''}Positive values favor ${g.home.name}; negative values favor ${g.away.name}.`,{class:'small-note'}));
    }
    el('season').addEventListener('change',loadSeason);
    el('source').addEventListener('change',resetFilters);
    for(const k of ['week','team'])el(k).addEventListener('change',render);
    el('edition').addEventListener('change',()=>renderDetail(true));
    coverageControl.addEventListener('change',()=>renderDetail(true));
    doc.addEventListener('cfb:lookback-activate',activate);
    doc.addEventListener('cfb:lookback-reload',()=>{++generation;++turn;cache.clear();index=null;report=null;rows=[];selected=null;pending=null;if(active)return activate();});
    return {activate};
  }
  return {predictions,missed,winner,summarize,mount};
});
