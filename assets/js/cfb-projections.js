/* Predictive power, independent of the merit ranker. Saved data; no model/API calls. */
(function (host, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else { host.CFBProjections = api; api.mount(document); }
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  const schema = 'cfb-projections-v1';
  const mean = x => x.reduce((a,b) => a+b,0)/x.length;
  const quantile = (sorted,p) => {const i=(sorted.length-1)*p, lo=Math.floor(i);return sorted[lo]+(sorted[Math.ceil(i)]-sorted[lo])*(i-lo);};
  function lgamma(x) {
    const c=[76.18009172947146,-86.50532032941677,24.01409824083091,-1.231739572450155,.001208650973866179,-.000005395239384953];
    let y=x,t=x+5.5,s=1.000000000190015;t-=(x+.5)*Math.log(t);
    for(const a of c)s+=a/++y;return -t+Math.log(2.5066282746310005*s/x);
  }
  function betacf(a,b,x) {
    const tiny=1e-30;let c=1,d=1-(a+b)*x/(a+1);if(Math.abs(d)<tiny)d=tiny;d=1/d;let h=d;
    for(let m=1;m<=200;m++) {
      const m2=2*m;
      const terms=[m*(b-m)*x/((a-1+m2)*(a+m2)),-(a+m)*(a+b+m)*x/((a+m2)*(a+1+m2))];
      for(let j=0;j<2;j++) {const aa=terms[j];
        d=1+aa*d;if(Math.abs(d)<tiny)d=tiny;c=1+aa/c;if(Math.abs(c)<tiny)c=tiny;d=1/d;
        const delta=d*c;h*=delta;
        if(j===1&&Math.abs(delta-1)<3e-12)return h;
      }
    }
    return h;
  }
  function tcdf(t,nu) {
    const x=nu/(nu+t*t),a=nu/2,b=.5;
    if(x>=1)return .5;
    const factor=Math.exp(lgamma(a+b)-lgamma(a)-lgamma(b)+a*Math.log(x)+b*Math.log1p(-x));
    const beta=x<(a+1)/(a+b+2)?factor*betacf(a,b,x)/a:1-factor*betacf(b,a,1-x)/b;
    return Math.max(0,Math.min(1,t>=0?1-beta/2:beta/2));
  }
  function validateDraws(d) {
    const n=d.sigma?.length;
    if(d.schema!==schema||!Number.isInteger(n)||n<100||!d.home?.national||!d.noise||d.noise.length!==2)
      throw new Error('Invalid saved forecast draws');
    for(const v of [...Object.values(d.teams),...Object.values(d.home),d.sigma,d.nu,...d.noise])
      if(!Array.isArray(v)||v.length!==n||v.some(x=>!Number.isFinite(x)))throw new Error('Forecast draws do not align');
    if(d.sigma.some(x=>x<=0)||d.nu.some(x=>x<=2))throw new Error('Invalid predictive scale');
    if(d.means)for(const key of ['teams','home'])for(const id of Object.keys(d[key]))
      if(!Number.isFinite(d.means[key]?.[id]))throw new Error('Missing full-draw means');
    return d;
  }
  function matchup(d,home,away,neutral) {
    if(home===away||!d.teams[home]||!d.teams[away])throw new Error('Choose two different teams.');
    const h=d.teams[home],a=d.teams[away],n=h.length;
    const strength=h.map((v,i)=>v-a[i]);
    const loc=strength.map((v,i)=>v+(neutral?0:d.home.national[i]+(d.home[home]?.[i]||0)));
    const pred=loc.flatMap((v,i)=>[v+d.noise[0][i],v+d.noise[1][i]]).sort((a,b)=>a-b);
    const p=mean(loc.map((v,i)=>tcdf(v/d.sigma[i],d.nu[i])));
    const sorted=[...loc].sort((a,b)=>a-b),margin=d.means?d.means.teams[home]-d.means.teams[away]
      +(neutral?0:d.means.home.national+(d.means.home[home]||0)):mean(loc);
    return {margin,homeLine:-margin,pHome:p,pAway:1-p,pBetter:mean(strength.map(v=>v>0?1:v===0?.5:0)),
      expectedMedian:quantile(sorted,.5),expected80:[quantile(sorted,.1),quantile(sorted,.9)],
      range80:[quantile(pred,.1),quantile(pred,.9)],range95:[quantile(pred,.025),quantile(pred,.975)],
      homeDraws:h,awayDraws:a,pred};
  }
  function mount(doc) {
    const root=doc.querySelector('[data-cfb-projections]');if(!root)return;
    const el=k=>root.querySelector(`[data-projection-${k}]`);
    const main=doc.querySelector('[data-cfb-product-panel="merit"]');
    const buttons=[...doc.querySelectorAll('[data-cfb-product-tab]')];
    const node=(tag,text,attrs={})=>{const n=doc.createElement(tag);if(text!=null)n.textContent=text;for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
    const svg=(tag,attrs,text)=>{const n=doc.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;return n;};
    const fmt=v=>Number.isFinite(v)?v.toFixed(1):'—';
    const sign=v=>`${v>0?'+':''}${fmt(v)}`;
    const pct=v=>v>.995?'>99%':v<.005?'<1%':`${(100*v).toFixed(1)}%`;
    const date=v=>new Date(v).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric',timeZone:'America/New_York'});
    const interval=v=>`${sign(v[0])} to ${sign(v[1])}`;
    const cache=new Map();let index,data,draws,sequence=0,initializing=null;
    const base=new URL('./',new URL(root.dataset.index,location.href));
    function read(file) {
      if(!/^[a-z0-9-]+\.json$/.test(file))return Promise.reject(new Error('Invalid forecast file'));
      if(!cache.has(file)) {
        const pending=(async()=>{const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),20000);
          try {const r=await fetch(new URL(file,base),{signal:abort.signal,cache:file==='index.json'?'no-cache':'default'});
            if(!r.ok)throw new Error('The saved projections could not be loaded.');return await r.json();
          } finally {clearTimeout(timer);}})();
        cache.set(file,pending);pending.catch(()=>cache.delete(file));
      }
      return cache.get(file);
    }
    function activate(name,focus=false) {
      main.hidden=name!=='merit';root.hidden=name!=='projections';
      buttons.forEach(b=>{const chosen=b.dataset.cfbProductTab===name;b.setAttribute('aria-selected',String(chosen));b.tabIndex=chosen?0:-1;if(chosen&&focus)b.focus();});
      if(name==='projections') {history.replaceState(null,'',`${location.pathname}${location.search}#projections`);initialize();}
      else {if(location.hash==='#projections')history.replaceState(null,'',`${location.pathname}${location.search}#rankings`);doc.dispatchEvent(new Event('cfb:merit-activate'));}
    }
    buttons.forEach((b,i)=>{b.addEventListener('click',()=>activate(b.dataset.cfbProductTab));b.addEventListener('keydown',e=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();
      const j=e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
      activate(buttons[j].dataset.cfbProductTab,true);});});
    window.addEventListener('hashchange',()=>activate(location.hash==='#projections'?'projections':'merit'));
    doc.querySelectorAll('.cfb-jumps a[href^="#"]').forEach(a=>a.addEventListener('click',()=>activate(a.getAttribute('href')==='#projections'?'projections':'merit')));
    function line(m) {const v=Math.round(Math.abs(m)*2)/2;return !v?'Pick’em':`${team(m>0?el('home').value:el('away').value)} −${v.toFixed(1)}`;}
    const team=id=>data.teams.find(t=>t.id===id)?.name||id;
    function table(target,heads,rows) {
      const table=node('table'),head=node('thead'),tr=node('tr'),body=node('tbody');
      heads.forEach(h=>tr.append(node('th',h,{scope:'col'})));head.append(tr);
      rows.forEach(cells=>{const r=node('tr');cells.forEach(c=>{const td=node('td');td.append(typeof c==='object'?c:doc.createTextNode(String(c)));r.append(td);});body.append(r);});
      table.append(head,body);target.replaceChildren(table);
    }
    function histogram(target,series,label) {
      const width=640,height=245,left=50,right=620,top=20,bottom=205;
      const all=series.flatMap(s=>s.values),sorted=[...all].sort((a,b)=>a-b);
      let lo=quantile(sorted,.005),hi=quantile(sorted,.995);if(hi-lo<.001){lo-=1;hi+=1;}
      const bins=36,step=(hi-lo)/bins;
      const counts=series.map(s=>{const c=Array(bins).fill(0);s.values.forEach(v=>{if(v>=lo&&v<=hi)c[Math.min(bins-1,Math.floor((v-lo)/step))]++;});return c.map(v=>v/s.values.length);});
      const max=Math.max(...counts.flat(),.001),x=v=>left+(v-lo)/(hi-lo)*(right-left),y=v=>bottom-v/max*(bottom-top);
      const plot=svg('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':label});plot.append(svg('title',{},label));
      for(let i=0;i<=4;i++){const yy=y(max*i/4);plot.append(svg('line',{x1:left,x2:right,y1:yy,y2:yy,stroke:'#d2dfe8'}));plot.append(svg('text',{x:left-8,y:yy+4,'text-anchor':'end'},`${(100*max*i/4).toFixed(0)}%`));}
      counts.forEach((c,j)=>c.forEach((v,i)=>plot.append(svg('rect',{x:x(lo+i*step),y:y(v),width:(right-left)/bins,height:bottom-y(v),fill:series[j].color,opacity:.55}))));
      if(lo<0&&hi>0)plot.append(svg('line',{x1:x(0),x2:x(0),y1:top,y2:bottom,stroke:'#142f43','stroke-dasharray':'4 4'}));
      for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4;plot.append(svg('text',{x:x(v),y:bottom+23,'text-anchor':'middle'},v.toFixed(0)));}
      target.replaceChildren(plot,node('p',series.map(s=>s.name).join(' / ')+' · share of draws per bin; plot shows the central 99%.',{class:'small-note'}));
    }
    function renderMatchup() {
      if(!draws)return;
      try {
        const h=el('home').value,a=el('away').value,r=matchup(draws,h,a,el('site').value==='neutral');
        // Retain the full-draw probabilities for a scheduled matchup.
        const official=data.games.find(g=>g.home===h&&g.away===a&&g.neutral===(el('site').value==='neutral'));
        if(official){r.pHome=official.p_home;r.pAway=1-official.p_home;}
        el('matchup-error').textContent='';el('matchup-result').hidden=false;
        el('line').textContent=line(r.margin);el('home-chance').textContent=pct(r.pHome);el('away-chance').textContent=pct(r.pAway);
        el('home-label').textContent=`${team(h)} wins`;el('away-label').textContent=`${team(a)} wins`;
        el('range').textContent=interval(r.range80);
        el('range-label').textContent=`80% range · ${team(h)}’s final margin`;
        el('matchup-note').textContent=`${team(h)}’s expected margin: ${sign(r.margin)} points (posterior median ${sign(r.expectedMedian)}; 80% interval ${interval(r.expected80)}). Its chance of being the stronger team on a neutral field is ${pct(r.pBetter)}. The 95% range for an actual game is ${interval(r.range95)} points. Positive margins favor ${team(h)}; negative margins favor ${team(a)}.`;
        histogram(el('strength-chart'),[{name:team(h)+' (blue)',values:r.homeDraws,color:'#245a82'},{name:team(a)+' (gold)',values:r.awayDraws,color:'#b67d25'}],'Uncertainty in the two teams’ power estimates, in points');
        histogram(el('margin-chart'),[{name:`${team(h)}’s final margin`,values:r.pred,color:'#245a82'}],'Posterior predictive distribution of the final score margin');
      } catch(e){el('matchup-result').hidden=true;el('matchup-error').textContent=e.message;}
    }
    function renderGames() {
      if(!data)return;const week=el('week').value,q=el('search').value.trim().toLowerCase();
      const rows=data.games.filter(g=>(!week||`${g.season_type}:${g.week}`===week)&&(!q||`${team(g.home)} ${team(g.away)}`.toLowerCase().includes(q)));
      table(el('games'),['Date','Matchup','Model line','Home win','Away win','80% final-margin range (home)'],rows.map(g=>{
        const b=node('button',`${team(g.away)} ${g.neutral?'vs.':'at'} ${team(g.home)}`,{type:'button',class:'cfb-forecast-game'});
        b.addEventListener('click',()=>{el('home').value=g.home;el('away').value=g.away;el('site').value=g.neutral?'neutral':'home';renderMatchup();el('matchup').scrollIntoView({behavior:'smooth',block:'start'});});
        const by=Math.round(Math.abs(g.home_margin)*2)/2;
        return [date(g.date),b,by?`${team(g.home_margin>0?g.home:g.away)} −${by.toFixed(1)}`:'Pick’em',pct(g.p_home),pct(1-g.p_home),interval([g.margin_lo80,g.margin_hi80])];
      }));
      el('games-note').textContent=rows.length?`${rows.length} scheduled games in this saved forecast. Select a game to explore it below.`:'No upcoming games match this selection in this saved snapshot.';
    }
    function renderRatings() {
      if(!data)return;const q=el('power-search').value.trim().toLowerCase(),conf=el('conference').value;
      const rows=data.ratings.filter(r=>(!conf||r.conference===conf)&&(!q||r.name.toLowerCase().includes(q)));
      const shown=el('limit').value==='all'?rows:rows.slice(0,25);
      table(el('powers'),['Power order','Team','Mean (pts)','Median','95% interval','80% order range','P(best)','P(top 4)','P(top 12)','P(top 25)'],shown.map(r=>[r.position,r.name,sign(r.mean),sign(r.median),interval([r.lo95,r.hi95]),`${r.rank_lo80.toFixed(0)}–${r.rank_hi80.toFixed(0)}`,pct(r.p_top1),pct(r.p_top4),pct(r.p_top12),pct(r.p_top25)]));
      el('power-count').textContent=`Showing ${shown.length} of ${rows.length} matching FBS teams. Order is by posterior mean power; probabilities describe strength, not playoff qualification.`;
    }
    async function selectSnapshot(id) {
      const turn=++sequence;draws=null;el('content').hidden=true;el('status').textContent='Loading saved projections…';
      try {
        const row=index.snapshots.find(r=>r.id===id);if(!row)throw new Error('Unknown forecast snapshot');
        const value=await read(row.file);if(turn!==sequence)return;
        if(value.schema!==schema||!value.ratings?.length||!Array.isArray(value.games))throw new Error('Invalid forecast snapshot');
        data=value;el('snapshot').value=id;
        const m=data.meta;
        el('asof').textContent=`${m.season} season · fit includes results through ${date(m.through_date)} (week ${m.week}) · ${m.games_used.toLocaleString()} games · ${m.draws.toLocaleString()} posterior draws.`;
        el('snapshot-note').textContent=`Schedule observed ${date(m.observed_at)}. This is a saved forecast, not a live score feed. Games and estimates do not change while you browse.`;
        el('prior-caveat').textContent=m.prior_caveat||'';
        const teams=[...data.teams].sort((a,b)=>a.division.localeCompare(b.division)||a.name.localeCompare(b.name));
        for(const key of ['home','away'])el(key).replaceChildren(...teams.map(t=>node('option',t.name+(t.division==='fcs'?' (FCS)':''),{value:t.id})));
        const first=data.games[0];el('home').value=first?.home||data.ratings[0].id;el('away').value=first?.away||data.ratings[1].id;el('site').value=first?.neutral?'neutral':'home';
        const weeks=[...new Set(data.games.map(g=>`${g.season_type}:${g.week}`))];
        el('week').replaceChildren(node('option','All upcoming games',{value:''}),...weeks.map(w=>node('option',`${w.startsWith('postseason')?'Postseason':'Week'} ${w.split(':')[1]}`,{value:w})));
        el('week').value=weeks[0]||'';
        el('conference').replaceChildren(node('option','All conferences',{value:''}),...[...new Set(data.ratings.map(r=>r.conference))].sort().map(c=>node('option',c,{value:c})));
        el('content').hidden=false;el('status').textContent='';renderGames();renderRatings();
        const diag=m.diagnostics;
        el('diagnostics').textContent=`${m.source}. ${diag.scope||'All retained parameters were checked for convergence and effective sample size.'} Maximum ${diag.max_rhat_theta!=null?'theta ':''}R̂: ${(diag.max_rhat_theta??diag.max_rank_normalized_rhat).toFixed(4)}. Divergences: ${diag.divergences}. Home-field history: ${m.home_years.join(', ')}. Preseason coefficients trained on ${m.prior_training_seasons.join(', ')}.`;
        el('draw-note').textContent='Loading saved draws for the matchup tool…';el('matchup-result').hidden=true;
        const loaded=validateDraws(await read(data.draws_file));if(turn!==sequence)return;draws=loaded;
        el('draw-note').textContent=`Model lines and scheduled-game probabilities use all ${m.draws.toLocaleString()} draws. Other matchup probabilities and charts use ${m.matchup_draws.toLocaleString()} aligned draws, with two simulated games per draw; these are numerical approximations. No model is run in your browser.`;
        renderMatchup();
      } catch(e){if(turn===sequence){el('status').textContent=`${e.message} Use Reload to try again.`;el('draw-note').textContent='Matchup draws unavailable.';}}
    }
    async function initialize() {
      if(initializing)return initializing;
      initializing=(async()=>{try{
        index=await read('index.json');if(index.schema!==schema||!index.snapshots?.length)throw new Error('No saved projections yet.');
        el('snapshot').replaceChildren(...index.snapshots.map(r=>node('option',`${r.season} · week ${r.week} · ${date(r.through_date)}${r.id===index.latest?' · latest':''}`,{value:r.id})));
        await selectSnapshot(index.latest);
        const back=await read('backtest.json');
        const h=back.headline[0];
        el('backtest-summary').textContent=`Supplied retrospective backtest, 2022–2025: ${h.n_games.toLocaleString()} games with closing lines. Model average absolute miss: ${fmt(h.model_mae)} points; closing-line miss: ${fmt(h.book_mae)} points. Smaller is better. These are development-period comparisons, not a prospective guarantee.`;
        table(el('backtest'),['Weeks','Games','Model miss (pts)','Closing-line miss (pts)','Difference'],back.phase_final.map(r=>[r.phase,r.n,fmt(r.mae),fmt(r.mae_book_same),sign(r.gap)]));
      }catch(e){el('status').textContent=`${e.message} Use Reload to try again.`;initializing=null;}})();
      return initializing;
    }
    el('snapshot').addEventListener('change',()=>selectSnapshot(el('snapshot').value));
    el('reload').addEventListener('click',()=>{cache.delete('index.json');initializing=null;initialize();});
    for(const key of ['home','away','site'])el(key).addEventListener('change',renderMatchup);
    el('swap').addEventListener('click',()=>{const h=el('home').value;el('home').value=el('away').value;el('away').value=h;renderMatchup();});
    for(const key of ['week','search'])el(key).addEventListener(key==='search'?'input':'change',renderGames);
    for(const key of ['conference','limit','power-search'])el(key).addEventListener(key==='power-search'?'input':'change',renderRatings);
    activate(location.hash==='#projections'?'projections':'merit');
  }
  return {tcdf,matchup,validateDraws,mount};
});
