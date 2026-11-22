/* Joint conference summaries are saved with each week; no browser inference. */
window.CFBConferences = (root, {node, svg, chart, num, interval}) => {
  const el = name => root.querySelector(`[data-cfb-conf-${name}]`);
  const percent = x => `${(100*x).toFixed(1)}%`;
  let current, data, active = false;
  function choices() {
    const rows = data?.conferences || [], a = el('a'), b = el('b');
    const priorA = a.value, priorB = b.value;
    a.replaceChildren(...rows.map(r => node('option', r.name, {value:r.name})));
    a.value = rows.some(r => r.name===priorA) ? priorA
      : rows.find(r => /^(SEC|Southeastern)$/i.test(r.name))?.name || rows[0]?.name || '';
    b.replaceChildren(...rows.filter(r => r.name!==a.value).map(r => node('option', r.name, {value:r.name})));
    b.value = rows.some(r => r.name===priorB && r.name!==a.value) ? priorB
      : rows.find(r => /^(Big Ten|Big 10|B1G)$/i.test(r.name) && r.name!==a.value)?.name
        || rows.find(r => r.name!==a.value)?.name || '';
    a.disabled = !rows.length; b.disabled = rows.length<2;
  }
  function distribution(summary, label) {
    const h = summary.distribution, points = h.edges || h.x;
    const heights = h.counts.map((v,i) => v / summary.n / (h.kind==='histogram' ? h.edges[i+1]-h.edges[i] : 1));
    const {plot,x,y,top,bottom} = chart(el('plot'), label,
      Math.min(0,...points), Math.max(0,...points), 0, Math.max(...heights)*1.12);
    plot.append(svg('text', {x:57,y:14}, h.kind==='histogram'?'Density':'Probability mass'));
    h.counts.forEach((count,i) => {
      const low=points[i], high=h.kind==='histogram'?points[i+1]:low;
      const bar=h.kind==='histogram'
        ? svg('rect',{x:x(low),width:Math.max(.1,x(high)-x(low)),y:y(heights[i]),height:bottom-y(heights[i]),fill:'#245a82',opacity:.4})
        : svg('line',{x1:x(low),x2:x(low),y1:bottom,y2:y(heights[i]),stroke:'#245a82','stroke-width':5});
      bar.append(svg('title',{},`${num(low)}${low===high?'':' to '+num(high)} points: ${percent(count/summary.n)}`));
      plot.append(bar);
    });
    for (const [value,color,dash,labelText] of [[0,'#78818b','3 3','Equal strength'],[summary.mean,'#245a82','','Mean'],[summary.median,'#245a82','6 3','Median']]) {
      const line=svg('line',{x1:x(value),x2:x(value),y1:top,y2:bottom,stroke:color,'stroke-width':1.5,'stroke-dasharray':dash});
      line.append(svg('title',{},`${labelText}: ${num(value)}`)); plot.append(line);
    }
  }
  function render() {
    if (!active || !current) return;
    el('rows').replaceChildren(); el('pair').replaceChildren(); el('plot').replaceChildren(); el('members').replaceChildren();
    el('plot-note').textContent = '';
    const valid=data?.schema==='margin-of-merit-conferences-v1' && Array.isArray(data.conferences) && data.conferences.length;
    el('content').hidden = !valid;
    el('status').textContent = valid
      ? `${current.season} · through Week ${current.week}. Strength estimates use all eligible games through this cutoff. The merit reference and ordering controls do not affect this tab.`
      : 'Conference comparisons have not been saved for this update yet. They will appear as the weekly results are regenerated; existing team rankings remain available.';
    if (!valid) return;
    const key=el('metric').value, rows=[...data.conferences].sort((a,b)=>b.metrics[key].strength.mean-a.metrics[key].strength.mean||a.name.localeCompare(b.name));
    el('context').textContent = key==='roster'
      ? 'Average the estimated strengths of all FBS members in each draw, giving every team equal weight. +3 means this conference’s average team is estimated three points above the average FBS team on a neutral field. A bigger conference gets no automatic bonus.'
      : 'The shared conference baseline from the hierarchical model, before adding each school’s deviation. It estimates the underlying conference level with partial pooling; it can differ from the average of this season’s actual teams. Values are relative to the same average FBS team.';
    for (const row of rows) {
      const m=row.metrics[key], tr=node('tr');
      tr.append(node('td',m.point_rank));
      const label=node('td'), button=node('button',row.name,{type:'button',class:'cfb-inline-button'});
      button.addEventListener('click',()=>{el('a').value=row.name;choices();render();}); label.append(button); tr.append(label);
      for (const v of [`${row.teams_with_games}/${row.teams}`, num(m.strength.mean), num(m.strength.median), interval(m.strength.q05,m.strength.q95),
                       `${num(m.rank.mean)} (${interval(m.rank.q05,m.rank.q95)})`,percent(m.p_best)]) tr.append(node('td',v));
      el('rows').append(tr);
    }
    const independentNames=current.teams.filter(t=>data.independent_team_ids.includes(t.id)).map(t=>t.name);
    el('coverage').textContent = `Membership follows the selected season. “Played / members” counts teams with at least one eligible game; teams without games still contribute their uncertain strength estimates. FCS teams inform the joint model but are not ranked here.${independentNames.length?' Independents are not a conference and are excluded from this table: '+independentNames.join(', ')+'.':''}`;
    const a=el('a').value,b=el('b').value;
    for (const name of [a,b].filter(Boolean)) {
      const row=rows.find(r=>r.name===name);
      el('members').append(node('p',`${name}: ${current.teams.filter(t=>row.team_ids.includes(t.id)).map(t=>t.name).sort().join(', ')}.`));
    }
    if (!b) {el('pair').append(node('p','This snapshot has only one eligible conference; no pairwise comparison is available.'));return;}
    const pair=data.comparisons[key][a][b], reverse=data.comparisons[key][b][a], s=pair.difference;
    el('pair').append(node('h4',`${a} − ${b}`),node('p',`Estimated gap: ${num(s.mean)} points (posterior mean); median ${num(s.median)}; 90% credible interval ${interval(s.q05,s.q95)} points.`),
      node('p',`P(${a} stronger) = ${percent(pair.p_greater)} · P(${b} stronger) = ${percent(reverse.p_greater)}${pair.p_equal>0?' · Equal in '+percent(pair.p_equal)+' of draws':''}.`),
      node('p',`${s.q05<=0&&s.q95>=0?'The 90% interval includes zero: both directions remain within that interval.':'The 90% interval lies entirely '+(s.q05>0?'above':'below')+' zero.'} These are probabilities about the selected conference strength measure under this model, not the chance of winning a particular game.`));
    distribution(s,`${a} minus ${b}: posterior distribution of the ${key==='roster'?'average team strength':'conference baseline'} gap in points`);
    el('plot-note').textContent = `Positive values favor ${a}; negative values favor ${b}. Blue solid line = mean; blue dashed = median; gray dotted = equal strength. Differences are calculated within each of the ${s.n.toLocaleString()} shared posterior draws, preserving their dependence. The histogram bins the draws; summaries use their full precision.`;
  }
  el('a').addEventListener('change',()=>{choices();render();});
  for (const key of ['b','metric']) el(key).addEventListener('change',render);
  return {show(value) {current=value;data=value.posterior?.conferences;choices();render();},
    tab(name) {active=name==='conferences';render();}, resize:render};
};
