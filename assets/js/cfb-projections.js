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
  function normalLogSurvival(x) {
    if(x<0)return Math.log1p(-Math.exp(normalLogSurvival(-x)));
    if(x>=8) {
      let tail=0;for(let k=40;k>=1;k--)tail=k/(x+tail);
      return -.5*x*x-.9189385332046727-Math.log(x+tail);
    }
    const z=x/Math.SQRT2,t=1/(1+.5*z);
    return Math.min(-Math.LN2,Math.log(t)-z*z-1.26551223+t*(1.00002368+t*(.37409196+t*(.09678418+t*(-.18628806+t*(.27886807+t*(-1.13520398+t*(1.48851587+t*(-.82215223+t*.17087277))))))))-Math.LN2);
  }
  function inverseLogSurvival(logp) {
    let z=logp< -Math.LN2?Math.sqrt(-2*logp):-Math.sqrt(-2*Math.log(-Math.expm1(logp)));
    for(let j=0;j<20;j++) {
      const logsf=normalLogSurvival(z),step=(logsf-logp)/Math.exp(-.5*z*z-.9189385332046727-logsf);
      z+=step;if(Math.abs(step)<1e-11)break;
    }
    return z;
  }
  function scoreOutcomes(s,home,away,margins) {
    const h=[],a=[];
    margins.forEach((m,k)=>{
      const i=Math.floor(k/2),j=k%2,scale=s.scale[i];
      const mu=s.intercept[i]+s.teams[home][i]+s.teams[away][i]+s.slope[i]*(Math.abs(m)-14)/14;
      const logq=normalLogSurvival(-mu/scale)+Math.log1p(-s.uniform[j][i]);
      const lower=mu+scale*inverseLogSurvival(logq);
      if(!Number.isFinite(lower)||lower< -1e-6)throw new Error('Invalid saved score simulation');
      h.push(Math.max(0,lower)+Math.max(m,0));a.push(Math.max(0,lower)+Math.max(-m,0));
    });
    const summarize=v=>{const sorted=[...v].sort((a,b)=>a-b);return {mean:mean(v),median:quantile(sorted,.5),
      lo80:quantile(sorted,.1),hi80:quantile(sorted,.9),lo95:quantile(sorted,.025),hi95:quantile(sorted,.975)};};
    return {home:summarize(h),away:summarize(a),homeDraws:h,awayDraws:a};
  }
  function validateDraws(d) {
    if(!d.teams&&d.last&&d.drift)d.teams=Object.fromEntries(Object.entries(d.last).map(([id,x])=>[id,x.map((v,i)=>v+d.drift[id][i])]));
    const n=d.sigma?.length;
    if(d.schema!==schema||!Number.isInteger(n)||n<100||!d.home?.national||!d.noise||d.noise.length!==2)
      throw new Error('Invalid saved forecast draws');
    for(const v of [...Object.values(d.teams),...Object.values(d.home),d.sigma,d.nu,...d.noise,...Object.values(d.last||{}),...Object.values(d.drift||{}),...(d.lam?[d.lam]:[])])
      if(!Array.isArray(v)||v.length!==n||v.some(x=>!Number.isFinite(x)))throw new Error('Forecast draws do not align');
    if(d.last&&Object.keys(d.teams).some(id=>!d.last[id]||!d.drift?.[id]))throw new Error('Missing weekly drift draws');
    if(d.sigma.some(x=>x<=0)||d.nu.some(x=>x<=2))throw new Error('Invalid predictive scale');
    if(d.means)for(const key of d.last?['last','drift','home']:['teams','home'])for(const id of Object.keys(d[key]))
      if(!Number.isFinite(d.means[key]?.[id]))throw new Error('Missing full-draw means');
    if(d.scores) {
      const s=d.scores;
      if(s.version!=='conditional-scores-1'||s.uniform?.length!==2||Object.keys(d.teams).some(id=>!s.teams?.[id]))
        throw new Error('Incomplete saved score model');
      for(const v of [s.intercept,s.slope,s.scale,...Object.values(s.teams),...s.uniform])
        if(!Array.isArray(v)||v.length!==n||v.some(x=>!Number.isFinite(x)))throw new Error('Score draws do not align');
      if(s.scale.some(x=>x<=0)||s.uniform.some(v=>v.some(x=>x<=0||x>=1)))throw new Error('Invalid score simulation parameters');
    }
    return d;
  }
  function matchup(d,home,away,neutral,ahead=1,qbs={}) {
    if(home===away||!d.teams[home]||!d.teams[away])throw new Error('Choose two different teams.');
    if(!Number.isInteger(ahead)||ahead<1||ahead>52)throw new Error('Choose a horizon from 1 to 52 weeks.');
    const strengthAt=id=>d.last?d.last[id].map((v,i)=>v+Math.sqrt(ahead)*d.drift[id][i]):d.teams[id];
    const qx=(id,choice)=>{const q=d.quarterbacks?.[id];if(!q||choice==='mix')return 0;
      const x=choice?q.options?.[choice]:q.x;if(!Number.isFinite(x))throw new Error('Unknown quarterback scenario');return x;};
    const hx=qx(home,qbs.home),ax=qx(away,qbs.away),lam=d.lam||Array(d.sigma.length).fill(0);
    const baseH=strengthAt(home),baseA=strengthAt(away);
    const h=baseH.map((v,i)=>v+lam[i]*hx),a=baseA.map((v,i)=>v+lam[i]*ax),n=h.length;
    const strength=h.map((v,i)=>v-a[i]);
    const loc=strength.map((v,i)=>v+(neutral?0:d.home.national[i]+(d.home[home]?.[i]||0)));
    const paired=loc.flatMap((v,i)=>[v+d.noise[0][i],v+d.noise[1][i]]);
    const pred=[...paired].sort((a,b)=>a-b);
    const p=mean(loc.map((v,i)=>tcdf(v/d.sigma[i],d.nu[i])));
    const fullPower=(id,values)=>d.means?.last?d.means.last[id]+Math.sqrt(ahead)*d.means.drift[id]:(d.means?.teams?.[id]??mean(values));
    const lm=d.lambda_mean??mean(lam);
    const sorted=[...loc].sort((a,b)=>a-b),margin=d.means?fullPower(home,baseH)-fullPower(away,baseA)+lm*(hx-ax)
      +(neutral?0:d.means.home.national+(d.means.home[home]||0)):mean(loc);
    const result={margin,homeLine:-margin,pHome:p,pAway:1-p,pBetter:mean(strength.map(v=>v>0?1:v===0?.5:0)),
      expectedMedian:quantile(sorted,.5),expected80:[quantile(sorted,.1),quantile(sorted,.9)],
      range80:[quantile(pred,.1),quantile(pred,.9)],range95:[quantile(pred,.025),quantile(pred,.975)],
      homeDraws:h,awayDraws:a,pred,parts:{home:fullPower(home,baseH),away:fullPower(away,baseA),qbHome:lm*hx,qbAway:lm*ax,national:neutral?0:(d.means?.home.national??mean(d.home.national)),stadium:neutral?0:(d.means?.home[home]??mean(d.home[home]||Array(n).fill(0)))}};
    if(d.gaussian) {
      const g=d.gaussian,hg=g.teams[home],ag=g.teams[away],slot=Math.max(0,g.home_ids.indexOf(home));
      const national=neutral?0:g.home_mean[0],stadium=neutral||!slot?0:g.home_mean[slot];
      const m=hg.mean-ag.mean+national+stadium,v=hg.variance+ag.variance+(neutral?0:g.home_cov[0][0]+(slot?g.home_cov[slot][slot]+2*g.home_cov[0][slot]:0));
      const sd=Math.sqrt(v+g.sigma*g.sigma),p=tcdf(m/sd,1e7);
      Object.assign(result,{margin:m,homeLine:-m,pHome:p,pAway:1-p,pBetter:tcdf((hg.mean-ag.mean)/Math.sqrt(hg.variance+ag.variance),1e7),
        expectedMedian:m,expected80:[m-1.2815515655446004*Math.sqrt(v),m+1.2815515655446004*Math.sqrt(v)],
        range80:[m-1.2815515655446004*sd,m+1.2815515655446004*sd],range95:[m-1.959963984540054*sd,m+1.959963984540054*sd],
        parts:{home:hg.mean,away:ag.mean,national,stadium}});
    }
    if(d.scores)result.scores=scoreOutcomes(d.scores,home,away,paired);
    return result;
  }
  function mount(doc) {
    const root=doc.querySelector('[data-cfb-projections]');if(!root)return;
    const el=k=>root.querySelector(`[data-projection-${k}]`);
    const main=doc.querySelector('[data-cfb-product-panel="merit"]');
    const buttons=[...doc.querySelectorAll('[data-cfb-product-tab]')];
    const viewButtons=[...doc.querySelectorAll('[data-projection-view]')];
    const viewPanels=[...doc.querySelectorAll('[data-projection-panel]')];
    function selectView(name,focus=false) {
      viewPanels.forEach(p=>{p.hidden=p.dataset.projectionPanel!==name;});
      viewButtons.forEach(b=>{const chosen=b.dataset.projectionView===name;
        b.setAttribute('aria-selected',String(chosen));b.tabIndex=chosen?0:-1;
        if(chosen&&focus)b.focus();});
    }
    viewButtons.forEach((b,i)=>{
      b.addEventListener('click',()=>selectView(b.dataset.projectionView));
      b.addEventListener('keydown',e=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();
        const j=e.key==='Home'?0:e.key==='End'?viewButtons.length-1:(i+(e.key==='ArrowRight'?1:-1)+viewButtons.length)%viewButtons.length;
        selectView(viewButtons[j].dataset.projectionView,true);
      });
    });
    selectView('power');
    const node=(tag,text,attrs={})=>{const n=doc.createElement(tag);if(text!=null)n.textContent=text;for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
    const svg=(tag,attrs,text)=>{const n=doc.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;return n;};
    const fmt=v=>Number.isFinite(v)?v.toFixed(1):'—';
    const sign=v=>`${v>0?'+':''}${fmt(v)}`;
    const pct=v=>v>.995?'>99%':v<.005?'<1%':`${(100*v).toFixed(1)}%`;
    const date=v=>new Date(v).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric',timeZone:'America/New_York'});
    const interval=v=>`${sign(v[0])} to ${sign(v[1])}`;
    const scoreRange=(s,coverage)=>`${fmt(s['lo'+coverage])}–${fmt(s['hi'+coverage])}`;
    const cache=new Map();let index,data,draws,backtest,qbStatus,sequence=0,initializing=null;
    const base=new URL('./',new URL(root.dataset.index,location.href));
    function read(file) {
      if(!/^[a-z0-9-]+\.json$/.test(file))return Promise.reject(new Error('Invalid forecast file'));
      if(!cache.has(file)) {
        const pending=(async()=>{const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),20000);
          try {const r=await fetch(new URL(file,base),{signal:abort.signal,cache:['index.json','qb-status.json'].includes(file)?'no-cache':'default'});
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
    function predictedMargin(m,h,a) {return Math.abs(m)<.05?'Evenly matched':`${team(m>0?h:a)} by ${Math.abs(m).toFixed(1)} points`;}
    function scoreAvailability() {
      return el('snapshot').value===index.latest
        ? 'Team score predictions have not been published yet. Showing the latest available margins and win probabilities.'
        : 'This older forecast contains margins and win probabilities only.';
    }
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
        const h=el('home').value,a=el('away').value;
        for(const side of ['home','away']) {
          const id=el(side).value,sel=el(side+'-qb'),q=data.quarterbacks?.[id];
          if(sel.dataset.team!==id) {
            sel.replaceChildren(node('option',q?.name?`Expected: ${q.name}`:'No saved QB adjustment',{value:''}),
              node('option','Usual passer mix (zero adjustment)',{value:'mix'}),
              ...(q?.options||[]).map(p=>node('option',`${p.name} · ${p.dropbacks} dropbacks`,{value:p.id})));
            sel.value='';sel.dataset.team=id;
          }
          sel.disabled=!q?.options?.length;
        }
        const choices={home:el('home-qb').value,away:el('away-qb').value};
        const r=matchup(draws,h,a,el('site').value==='neutral',Number(el('horizon').value||1),choices);
        el('qb-note').textContent=data.quarterbacks?['home','away'].map(side=>{const q=data.quarterbacks[el(side).value];return `${team(el(side).value)}: ${q?.source||'unavailable'}${q?.note?' — '+q.note:''}.`;}).join(' ')+' QB selections are local scenarios; they do not update starter status.':'This older snapshot predates quarterback adjustments.';
        // Retain the full-draw probabilities for a scheduled matchup.
        const official=data.games.find(g=>g.home===h&&g.away===a&&g.neutral===(el('site').value==='neutral'));
        if(official&&!choices.home&&!choices.away&&(official.ahead||1)===Number(el('horizon').value||1)&&!draws.gaussian){r.pHome=official.p_home;r.pAway=1-official.p_home;}
        el('matchup-error').textContent='';el('matchup-result').hidden=false;
        el('line').textContent=predictedMargin(r.margin,h,a);el('home-chance').textContent=pct(r.pHome);el('away-chance').textContent=pct(r.pAway);
        el('home-label').textContent=`${team(h)} wins`;el('away-label').textContent=`${team(a)} wins`;
        el('range').textContent=interval(r.range80);
        el('range-label').textContent=`80% range · ${team(h)}’s final margin`;
        el('range95').textContent=interval(r.range95);
        el('range95-label').textContent=`95% range · ${team(h)}’s final margin`;
        el('scores').hidden=!r.scores;
        el('score-status').textContent=r.scores?'':scoreAvailability();
        if(r.scores) {
          el('home-score-label').textContent=team(h);el('away-score-label').textContent=team(a);
          el('home-score').textContent=Math.round(r.scores.home.mean);el('away-score').textContent=Math.round(r.scores.away.mean);
          table(el('score-summary'),['Team','Mean points','Median points','80% predictive range','95% predictive range'],
            [[h,r.scores.home],[a,r.scores.away]].map(([id,s])=>[team(id),fmt(s.mean),fmt(s.median),scoreRange(s,80),scoreRange(s,95)]));
          histogram(el('score-chart'),[{name:team(h)+' (blue)',values:r.scores.homeDraws,color:'#245a82'},
            {name:team(a)+' (gold)',values:r.scores.awayDraws,color:'#b67d25'}],'Predictive distributions of each team’s final points');
        }
        el('matchup-note').textContent=`${team(h)}’s expected margin: ${sign(r.margin)} points (posterior median ${sign(r.expectedMedian)}; 80% interval ${interval(r.expected80)}). Its chance of being the stronger team on a neutral field is ${pct(r.pBetter)}. The 95% range for an actual game is ${interval(r.range95)} points. Positive margins favor ${team(h)}; negative margins favor ${team(a)}.`;
        const parts=r.parts;
        table(el('line-parts'),['Component','Points toward home margin'],[[`${team(h)} usual-mix power`,sign(parts.home)],[`${team(a)} usual-mix power (subtracted)`,sign(-parts.away)],[`${team(h)} QB adjustment`,sign(parts.qbHome||0)],[`${team(a)} QB adjustment (subtracted)`,sign(-(parts.qbAway||0))],['National home advantage',sign(parts.national)],['Host’s additional advantage',sign(parts.stadium)],['Expected home margin',sign(r.margin)]]);
        renderDetails(h,a);
        histogram(el('strength-chart'),[{name:team(h)+' (blue)',values:r.homeDraws,color:'#245a82'},{name:team(a)+' (gold)',values:r.awayDraws,color:'#b67d25'}],'Uncertainty in the two teams’ power estimates, in points');
        histogram(el('margin-chart'),[{name:`${team(h)}’s final margin`,values:r.pred,color:'#245a82'}],'Posterior predictive distribution of the final score margin');
      } catch(e){el('matchup-result').hidden=true;el('matchup-error').textContent=e.message;}
    }
    function renderGames() {
      if(!data)return;const week=el('week').value,q=el('search').value.trim().toLowerCase();
      const rows=data.games.filter(g=>(!week||`${g.season_type}:${g.week}`===week)&&(!q||`${team(g.home)} ${team(g.away)}`.toLowerCase().includes(q)));
      const hasScores=data.games.length>0&&data.games.every(g=>g.scores?.home&&g.scores?.away);
      const columns=hasScores?['Home points · mean (80% range)','Away points · mean (80% range)']:['Predicted margin'];
      table(el('games'),['Date','Matchup',...columns,'Home win','Away win'],rows.map(g=>{
        const b=node('button',`${team(g.away)} ${g.neutral?'vs.':'at'} ${team(g.home)}`,{type:'button',class:'cfb-forecast-game'});
        b.addEventListener('click',()=>{el('home').value=g.home;el('away').value=g.away;el('home-qb').value='';el('away-qb').value='';el('site').value=g.neutral?'neutral':'home';el('horizon').value=String(g.ahead||1);selectView('compare');renderMatchup();el('matchup').scrollIntoView({behavior:'smooth',block:'start'});});
        const score=s=>`${fmt(s.mean)} (${scoreRange(s,80)})`;
        const prediction=hasScores?[score(g.scores.home),score(g.scores.away)]:[predictedMargin(g.home_margin,g.home,g.away)];
        return [date(g.date),b,...prediction,pct(g.p_home),pct(1-g.p_home)];
      }));
      el('games-note').textContent=rows.length
        ? (hasScores?'':scoreAvailability()+' ')+`${rows.length} scheduled games match your selection. `+(hasScores?'Point ranges include game-to-game variation. Select a game for score distributions, medians, and 95% ranges.':'Select a game to explore the predicted margin and its uncertainty.')
        : 'No upcoming games match your selection.';
    }
    function renderRatings() {
      if(!data)return;const q=el('power-search').value.trim().toLowerCase(),conf=el('conference').value;
      const rows=data.ratings.filter(r=>(!conf||r.conference===conf)&&(!q||r.name.toLowerCase().includes(q)));
      const shown=el('limit').value==='all'?rows:rows.slice(0,25);
      table(el('powers'),['Rank','Team','Record','Mean power','Median','95% interval','80% rank range','P(best)','P(top 4)','P(top 12)','P(top 25)'],shown.map(r=>{
        const name=node('button',r.name,{type:'button',class:'cfb-forecast-game','aria-label':`View details for ${r.name}`});
        name.addEventListener('click',()=>{el('home').value=r.id;
          if(el('away').value===r.id)el('away').value=data.ratings.find(t=>t.id!==r.id).id;
          el('home-qb').value='';el('away-qb').value='';
          el('site').value='neutral';el('horizon').value='1';selectView('compare',true);renderMatchup();
          if(draws&&!el('details-card').hidden){el('details-card').scrollIntoView({behavior:'smooth',block:'start'});el('detail-title').focus({preventScroll:true});}});
        return [r.position,name,Array.isArray(r.record)?r.record.join('–'):'—',sign(r.mean),sign(r.median),interval([r.lo95,r.hi95]),`${r.rank_lo80.toFixed(0)}–${r.rank_hi80.toFixed(0)}`,pct(r.p_top1),pct(r.p_top4),pct(r.p_top12),pct(r.p_top25)];
      }));
      el('power-count').textContent=`Showing ${shown.length} of ${rows.length} matching FBS teams. Order is by posterior mean power; probabilities describe strength, not playoff qualification.`;
      const qm=data.meta.quarterbacks;
      el('qb-status').textContent=qm?`QB play-by-play observed ${qm.observed_at?date(qm.observed_at):'before this season'}. ${qm.starter_rule} ${qm.missing_training_game_ids.length} training games lack usable passer data.${qm.warnings?.length?' A source refresh failed; the last usable data are shown.':''}`:'This saved forecast does not include the QB model.';
      if(qbStatus?.season===data.meta.season)el('qb-status').textContent+=` Last daily source check: ${date(qbStatus.checked_at)}.${qbStatus.warnings?.length?' Source refresh needs attention; saved estimates have been retained.':''}`;
    }
    function trajectory(target,path,label) {
      const w=640,h=240,l=48,r=620,top=20,b=205;
      let low=Math.min(...path.map(p=>p.mean-p.sd)),high=Math.max(...path.map(p=>p.mean+p.sd));if(high-low<1){low-=1;high+=1;}
      const x=i=>l+i*(r-l)/Math.max(1,path.length-1),y=v=>b-(v-low)/(high-low)*(b-top);
      const plot=svg('svg',{viewBox:`0 0 ${w} ${h}`,role:'img','aria-label':label});plot.append(svg('title',{},label));
      const band=path.map((p,i)=>`${x(i)},${y(p.mean+p.sd)}`).concat([...path].reverse().map((p,j)=>`${x(path.length-1-j)},${y(p.mean-p.sd)}`)).join(' ');
      plot.append(svg('polygon',{points:band,fill:'#d3e5f2'}));
      plot.append(svg('polyline',{points:path.map((p,i)=>`${x(i)},${y(p.mean)}`).join(' '),fill:'none',stroke:'#245a82','stroke-width':3}));
      path.forEach((p,i)=>plot.append(svg('text',{x:x(i),y:b+22,'text-anchor':'middle'},p.week)));
      for(let i=0;i<=4;i++){const v=low+(high-low)*i/4;plot.append(svg('text',{x:l-8,y:y(v)+4,'text-anchor':'end'},v.toFixed(0)));}
      target.append(plot,node('p','Week of season · line: posterior mean; band: ±1 posterior SD. All weeks use this snapshot’s evidence.',{class:'small-note'}));
    }
    function renderDetails(home,away) {
      const values=data.team_details||{};el('details-card').hidden=!data.team_details&&!data.quarterbacks;
      if(el('details-card').hidden)return;
      const labels={prev:'Last season’s strength',talent_z:'Roster talent (z-score)',ap:'Preseason AP points (log scale)',p4:'Conference-era indicator',rpc:'Returning offense share − 0.5',prev_rp:'Strength × returning production',rec_z:'Recruiting class (z-score)',newcoach:'New head coach',prev_coach:'Strength × coaching change',portal_z:'Transfer-portal points (z-score)',g5_prev:'Additional G5 carryover'};
      const cards=[home,away].map(id=>{const info=values[id],section=node('section');section.append(node('h4',team(id)));
        const quarterback=data.quarterbacks?.[id],rating=data.ratings.find(r=>r.id===id);
        if(quarterback) {
          section.append(node('h5','Quarterback contribution'));
          if(quarterback.starter) {
            const wrap=node('div',null,{class:'cfb-forecast-table',tabindex:'0'});
            const adjustment=rating?.qb_adjustment??data.meta.qb_lambda*quarterback.x;
            const rows=[['Expected quarterback',quarterback.name||`Passer ${quarterback.starter}`],['Contribution to power',sign(adjustment)]];
            if(rating)rows.push(['Power with usual passer mix',sign(rating.mean)],['Power with expected starter',sign(rating.rating_qb_now)]);
            table(wrap,['Detail','Estimate'],rows);section.append(wrap);
          } else section.append(node('p','No eligible current-season dropbacks are saved for this team, so there is no starter-specific adjustment in this forecast.'));
          section.append(node('p',`${quarterback.source}${quarterback.note?': '+quarterback.note:''}. Changing the quarterback above explores a scenario; these details show the saved forecast.`,{class:'small-note'}));
        }
        if(!info){section.append(node('p','Detailed inputs were not saved for this team.'));return section;}
        if(info.path?.length)trajectory(section,info.path,`${team(id)}’s estimated weekly strength`);
        const prior=node('details'),title=node('summary','Preseason inputs & contributions');prior.append(title);
        if(info.contributions){prior.append(node('p',`Prior mean ${sign(info.prior)} = average prior ${sign(info.prior_average)} plus the contributions below. These jointly fitted inputs overlap; a contribution is not a causal effect.`));
          const wrap=node('div',null,{class:'cfb-forecast-table',tabindex:'0'});table(wrap,['Input','Value','Prior contribution (pts)'],Object.entries(labels).map(([k,label])=>[label,fmt(info.inputs[k]),sign(info.contributions[k])]));prior.append(wrap);
        }else if(info.fcs_prior)prior.append(node('p',`FCS prior mean ${sign(info.fcs_prior.mean)} points, including a ${sign(info.fcs_prior.deviation)} deviation from the FCS average. Team-specific prior SD ${fmt(info.fcs_prior.sd)} points; uncertainty in the division average is additional.`));
        else prior.append(node('p','No FBS team-specific preseason regression prior was available. The model uses the relevant division prior.'));
        section.append(prior);
        const qi=data.qb_importance?.find(q=>q.team_id===id);
        if(qi)section.append(node('p',`QB importance: ${qi.qb} versus ${qi.backup} changes the estimate by ${sign(qi.importance_pts)} points, using ${fmt(qi.dropbacks_per_game)} dropbacks per game. This compares the last starter with the recent backup selected by the model; it is not an injury assessment.`));
        const games=node('details');games.append(node('summary','Game evidence in this fit'));
        const wrap=node('div',null,{class:'cfb-forecast-table',tabindex:'0'});
        table(wrap,['Week','Opponent','Venue','Actual margin','Blended margin','Opponent strength','Venue effect','QB effect','Game-implied strength'],info.games.map(g=>[g.week,team(g.opponent),g.site,sign(g.margin),sign(g.target),sign(g.opponent_strength),sign(g.home_edge),sign(g.qb_edge||0),sign(g.game_implied_strength)]));games.append(wrap);section.append(games);return section;});
      el('team-details').replaceChildren(...cards);
    }
    function renderErrorDistribution(row) {
      const bins=row.error_histogram,w=640,h=275,left=50,right=620,top=20,bottom=215;
      const lo=Math.min(0,bins.start),hi=Math.max(0,bins.start+bins.width*bins.counts.length);
      const peak=Math.max(...bins.counts)/row.n;
      const x=v=>left+(v-lo)/(hi-lo)*(right-left),y=v=>bottom-v/peak*(bottom-top);
      const plot=svg('svg',{viewBox:`0 0 ${w} ${h}`,role:'img','aria-label':'Distribution of past signed margin errors; dashed line: zero, gold line: average error'});
      plot.append(svg('title',{},'Predicted minus actual home margin in past games'));
      for(let i=0;i<=4;i++){const share=peak*i/4;
        plot.append(svg('line',{x1:left,x2:right,y1:y(share),y2:y(share),stroke:'#d2dfe8'}));
        plot.append(svg('text',{x:left-8,y:y(share)+4,'text-anchor':'end'},`${(100*share).toFixed(0)}%`));}
      bins.counts.forEach((count,i)=>plot.append(svg('rect',{x:x(bins.start+i*bins.width),y:y(count/row.n),
        width:x(lo+bins.width)-x(lo),height:bottom-y(count/row.n),fill:'#245a82',opacity:.65})));
      plot.append(svg('line',{x1:x(0),x2:x(0),y1:top,y2:bottom,stroke:'#142f43','stroke-width':2,'stroke-dasharray':'4 4'}));
      plot.append(svg('line',{x1:x(row.model_bias),x2:x(row.model_bias),y1:top,y2:bottom,stroke:'#b67d25','stroke-width':2}));
      for(let i=0;i<=4;i++){const value=lo+(hi-lo)*i/4;
        plot.append(svg('text',{x:x(value),y:bottom+22,'text-anchor':'middle'},value.toFixed(0)));}
      plot.append(svg('text',{x:(left+right)/2,y:h-8,'text-anchor':'middle'},'Predicted home margin − actual home margin (points)'));
      el('error-chart').replaceChildren(plot,node('p',`All ${row.n.toLocaleString()} games · bars: share of games in each ${bins.width}-point bin · dashed: zero error · gold: average signed error.`,{class:'small-note'}));
    }
    function renderEvaluation() {
      if(!backtest)return;
      const period=el('eval-period').value||'development',group=el('eval-group').value||'phase';
      const overall=backtest[period].phase.find(r=>r.group==='all');
      const ci=r=>Number.isFinite(r.model_mae_se)?`${fmt(Math.max(0,r.model_mae-1.96*r.model_mae_se))} to ${fmt(r.model_mae+1.96*r.model_mae_se)}`:'Not estimable from one week';
      el('backtest-summary').textContent=`${period==='development'?'2023–2025 development sample':'2026 retrospective reconstruction, through week '+backtest.through_week}: ${overall.n.toLocaleString()} games.`;
      const available=Number.isFinite(overall.model_bias)&&overall.error_histogram;
      el('error-summary').hidden=!available;
      if(available) {
        el('error-bias').textContent=`${sign(overall.model_bias)} points`;
        el('error-range80').textContent=interval([overall.error_lo80,overall.error_hi80]);
        el('error-range95').textContent=interval([overall.error_lo95,overall.error_hi95]);
        el('error-bias-note').textContent=Number.isFinite(overall.model_bias_se)
          ? `Approximate 95% confidence interval for the average signed error: ${interval([overall.model_bias-1.96*overall.model_bias_se,overall.model_bias+1.96*overall.model_bias_se])} points, using season-week clusters. This estimates uncertainty in the average, not variation between games.`
          : 'A cluster-based confidence interval for the average needs more than one season-week.';
        renderErrorDistribution(overall);
        table(el('evaluation'),['Group','Games','Average signed error (pts)','Middle 80% of errors (pts)','Middle 95% of errors (pts)'],backtest[period][group].map(r=>[
          r.group||'Unclassified',r.n,sign(r.model_bias),interval([r.error_lo80,r.error_hi80]),interval([r.error_lo95,r.error_hi95])]));
      } else el('backtest-summary').textContent+=' The signed-error summary has not been published for this report.';
      table(el('evaluation-technical'),['Group','Games','Margin MAE (pts)','95% confidence interval for MAE','Season-week clusters'],backtest[period][group].map(r=>[r.group||'Unclassified',r.n,fmt(r.model_mae),ci(r),r.clusters??'—']));
    }
    async function selectSnapshot(id) {
      const turn=++sequence;draws=null;el('content').hidden=true;el('status').textContent='Loading saved projections…';
      try {
        const row=index.snapshots.find(r=>r.id===id);if(!row)throw new Error('Unknown forecast snapshot');
        const value=await read(row.file);if(turn!==sequence)return;
        if(value.schema!==schema||!value.ratings?.length||!Array.isArray(value.games))throw new Error('Invalid forecast snapshot');
        data=value;el('snapshot').value=id;
        for(const side of ['home','away'])delete el(side+'-qb').dataset.team;
        const m=data.meta;
        el('horizon').disabled=!m.model;
        const horizons=[...new Set([1,2,3,4,6,8,12,...data.games.map(g=>g.ahead||1)])].sort((a,b)=>a-b);
        el('horizon').replaceChildren(...horizons.map(w=>node('option',w===1?'Next week':`${w} weeks ahead`,{value:String(w)})));
        el('horizon').value='1';
        el('asof').textContent=`${m.season} season · fit includes results through ${date(m.through_date)} (week ${m.week}) · ${m.games_used.toLocaleString()} games · ${m.draws.toLocaleString()} posterior draws.`;
        el('snapshot-note').textContent=(m.model?'':index.snapshots.some(r=>r.model)?'Archived forecast from an earlier model. ':'Archived earlier-model forecast. The updated forecasting model will appear after its first passing fit. ')+(!data.quarterbacks?'This saved forecast predates quarterback adjustments. ':'')+`Schedule observed ${date(m.observed_at)}. This is a saved forecast, not a live score feed. Games and estimates do not change while you browse.`;
        el('prior-caveat').textContent=m.prior_caveat||'';
        const teams=[...data.teams].sort((a,b)=>a.division.localeCompare(b.division)||a.name.localeCompare(b.name));
        for(const key of ['home','away'])el(key).replaceChildren(...teams.map(t=>node('option',t.name+(t.division==='fcs'?' (FCS)':''),{value:t.id})));
        const first=data.games[0];el('home').value=first?.home||data.ratings[0].id;el('away').value=first?.away||data.ratings[1].id;el('site').value=first?.neutral?'neutral':'home';el('horizon').value=String(first?.ahead||1);
        const weeks=[...new Set(data.games.map(g=>`${g.season_type}:${g.week}`))];
        el('week').replaceChildren(node('option','All upcoming games',{value:''}),...weeks.map(w=>node('option',`${w.startsWith('postseason')?'Postseason':'Week'} ${w.split(':')[1]}`,{value:w})));
        el('week').value=weeks[0]||'';
        el('conference').replaceChildren(node('option','All conferences',{value:''}),...[...new Set(data.ratings.map(r=>r.conference))].sort().map(c=>node('option',c,{value:c})));
        el('content').hidden=false;el('status').textContent='';renderGames();renderRatings();
        const diag=m.diagnostics;
        el('diagnostics').textContent=`${m.source}. ${diag.scope||'All retained parameters were checked for convergence and effective sample size.'} ${m.prior_only?'':`Maximum ${diag.max_rhat_theta!=null?'theta ':''}R̂: ${(diag.max_rhat_theta??diag.max_rank_normalized_rhat).toFixed(4)}. Divergences: ${diag.divergences}.`} Home-field history: ${m.home_years.join(', ')}. Preseason coefficients trained on ${m.prior_training_seasons.join(', ')}.`;
        el('draw-note').textContent='Loading saved draws for the matchup tool…';el('matchup-result').hidden=true;
        const loaded=validateDraws(await read(data.draws_file));if(turn!==sequence)return;draws=loaded;el('horizon').disabled=!draws.last;
        el('draw-note').textContent=draws.gaussian?'Preseason projections use the Gaussian approximation from the annual prior and home-field covariance. Charts use saved prior draws; no current-season sampler has run.':draws.last?`Power summaries, mean margins, and scheduled-game probabilities use all ${m.draws.toLocaleString()} draws. Other matchup probabilities, predictive ranges and charts use ${m.matchup_draws.toLocaleString()} aligned draws. Future drift grows with the selected horizon. These are numerical approximations; no model runs while you browse.`:`Mean margins and scheduled-game probabilities use all ${m.draws.toLocaleString()} draws. Other matchup probabilities, predictive ranges and charts use ${m.matchup_draws.toLocaleString()} aligned draws, with two simulated games per draw; these are numerical approximations. No model is run in your browser.`;
        renderMatchup();
      } catch(e){if(turn===sequence){el('status').textContent=`${e.message} Use Reload to try again.`;el('draw-note').textContent='Matchup draws unavailable.';}}
    }
    async function initialize() {
      if(initializing)return initializing;
      initializing=(async()=>{try{
        index=await read('index.json');if(index.schema!==schema||!index.snapshots?.length)throw new Error('No saved projections yet.');
        el('snapshot').replaceChildren(...index.snapshots.map(r=>node('option',`${r.season} · week ${r.week} · ${date(r.through_date)}${r.id===index.latest?' · latest':''}`,{value:r.id})));
        await selectSnapshot(index.latest);
        try{qbStatus=await read('qb-status.json');renderRatings();}catch(_){} // Not present in older deployments.
        backtest=await read('backtest.json');renderEvaluation();
      }catch(e){el('status').textContent=`${e.message} Use Reload to try again.`;initializing=null;}})();
      return initializing;
    }
    el('snapshot').addEventListener('change',()=>selectSnapshot(el('snapshot').value));
    el('reload').addEventListener('click',()=>{cache.delete('index.json');cache.delete('qb-status.json');qbStatus=null;initializing=null;initialize();});
    for(const key of ['home','away','site','horizon','home-qb','away-qb'])el(key).addEventListener('change',renderMatchup);
    for(const key of ['eval-period','eval-group'])el(key).addEventListener('change',renderEvaluation);
    el('swap').addEventListener('click',()=>{const h=el('home').value;el('home').value=el('away').value;el('away').value=h;renderMatchup();});
    for(const key of ['week','search'])el(key).addEventListener(key==='search'?'input':'change',renderGames);
    for(const key of ['conference','limit','power-search'])el(key).addEventListener(key==='power-search'?'input':'change',renderRatings);
    activate(location.hash==='#projections'?'projections':'merit');
  }
  return {tcdf,matchup,validateDraws,scoreOutcomes,mount};
});
