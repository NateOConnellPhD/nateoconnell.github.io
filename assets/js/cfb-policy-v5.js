/* FCS-aware policy replay; probabilities and raw merit remain immutable. */
((global)=>{
  'use strict';
  const defaults=Object.freeze({version:'margin-of-merit-order-2026-11-21-no-p4',merit_protection:.9,head_to_head:.95,common_opponents:.7,
    proximity:2,equal_records_only:true});
  const priorities={head_to_head:1,common_opponents:2,merit_protection:3};
  const sum=list=>list.reduce((a,b)=>a+b,0);
  async function run(input,settings=defaults,loadHighs,solverOptions={}) {
    const spec={...defaults,...settings};
    if(Object.keys(settings).some(key=>!Object.hasOwn(defaults,key))) throw Error('Unrecognized policy setting.');
    if(input?.schema!=='margin-of-merit-policy-input-v5'||spec.version!==defaults.version||!Number.isInteger(input.season)||input.season<2002)
      throw Error('Missing FCS-aware comparison inputs.');
    for(const key of ['merit_protection','head_to_head','common_opponents'])
      if(!Number.isFinite(spec[key])||spec[key]<.5||spec[key]>.99) throw Error('Thresholds must be between 50% and 99%.');
    if(!Number.isInteger(spec.proximity)||spec.proximity<0||spec.proximity>200) throw Error('Proximity must be an integer from 0 to 200.');
    if(typeof spec.equal_records_only!=='boolean') throw Error('Invalid policy toggle.');
    const {teams,opponents,means,probabilities:p}=input,n=teams.length,ids=teams.map(t=>t.id),index=new Map(ids.map((id,i)=>[id,i]));
    const all=teams.concat(opponents), known=new Set(all.map(t=>t.id));
    if(!n||index.size!==n||known.size!==all.length||all.some(t=>!Number.isInteger(t.id)||t.id<1||typeof t.name!=='string'||!t.name)||
        teams.some(t=>t.classification&&t.classification!=='fbs')||opponents.some(t=>t.classification!=='fcs')||means.length!==n||
        !means.every(Number.isFinite)||p.length!==n||p.some(row=>row.length!==n||row.some(x=>!Number.isFinite(x)||x<0||x>1))) throw Error('Invalid FBS/FCS comparison dimensions.');
    for(let i=0;i<n;i++) {if(p[i][i]!==0)throw Error('Expected strict greater-than probabilities.');
      for(let j=i+1;j<n;j++)if(p[i][j]+p[j][i]>1+1e-12)throw Error('Invalid pair probabilities.');}
    const wins=Array(n).fill(0),losses=Array(n).fill(0),vs=Array.from({length:n},()=>new Map());
    const seen=new Set(),games=[...input.games].sort((a,b)=>a.id-b.id);
    for(const g of games) {
      if(seen.has(g.id)||g.season!==input.season||!g.eligible||!g.completed||g.season_type!=='regular'||!known.has(g.home_id)||
        !known.has(g.away_id)||g.home_id===g.away_id||![g.home_points,g.away_points].every(x=>Number.isInteger(x)&&x>=0)||g.home_points===g.away_points)
        throw Error('Invalid saved game.');
      seen.add(g.id);
      for(const [id,opponent,won] of [[g.home_id,g.away_id,Number(g.home_points>g.away_points)],[g.away_id,g.home_id,Number(g.away_points>g.home_points)]]) {
        const i=index.get(id);if(i==null)continue;
        wins[i]+=won;losses[i]+=1-won;
        if(!vs[i].has(opponent))vs[i].set(opponent,[]);vs[i].get(opponent).push(won);
      }
    }
    const raw=ids.map((_,i)=>i).filter(i=>wins[i]+losses[i]).sort((i,j)=>means[j]-means[i]||ids[i]-ids[j]);
    const ranks=new Map(raw.map((i,k)=>[i,k+1])),audit=[],requirements=[];
    function decision(w,l,type,meta) {
      const row={type,priority:priorities[type],winner_id:ids[w],loser_id:ids[l],winner_record:[wins[w],losses[w]],loser_record:[wins[l],losses[l]],
        winner_raw_rank:ranks.get(w),loser_raw_rank:ranks.get(l),raw_rank_gap:Math.abs(ranks.get(w)-ranks.get(l)),p_loser_higher_merit:p[l][w],...meta};
      audit.push(row);if(row.eligible) requirements.push({before:ranks.get(w)-1,after:ranks.get(l)-1,priority:priorities[type]});
    }
    for(let a=0;a<raw.length;a++)for(let b=a+1;b<raw.length;b++) {
      const i=raw[a],j=raw[b];
      for(const [w,l]of [[i,j],[j,i]])if(p[w][l]>=spec.merit_protection)decision(w,l,'merit_protection',{
        eligible:true,qualification:'posterior_merit',threshold:spec.merit_protection});
      if(spec.equal_records_only&&(wins[i]!==wins[j]||losses[i]!==losses[j]))continue;
      let w,l,type;const direct=vs[i].get(ids[j])||[],meta={};
      if(direct.length) {
        const wi=sum(direct),wj=direct.length-wi;if(wi===wj)continue;
        [w,l]=wi>wj?[i,j]:[j,i];type='head_to_head';meta.direct_record=[Math.max(wi,wj),Math.min(wi,wj)];
        meta.game_ids=games.filter(g=>(g.home_id===ids[i]&&g.away_id===ids[j])||(g.home_id===ids[j]&&g.away_id===ids[i])).map(g=>g.id);
      } else {
        const shared=[...vs[i].keys()].filter(o=>vs[j].has(o)&&index.has(o)).sort((a,b)=>a-b);
        const delta=shared.map(o=>sum(vs[i].get(o))*vs[j].get(o).length-sum(vs[j].get(o))*vs[i].get(o).length);
        if(delta.some(d=>d>0)&&delta.every(d=>d>=0))[w,l]=[i,j];else if(delta.some(d=>d<0)&&delta.every(d=>d<=0))[w,l]=[j,i];
        if(w!=null) {
          type='common_opponents';meta.shared_results=shared.map(o=>({opponent_id:o,winner_wins:sum(vs[w].get(o)),winner_games:vs[w].get(o).length,
            loser_wins:sum(vs[l].get(o)),loser_games:vs[l].get(o).length}));
          meta.game_ids=games.filter(g=>(([ids[i],ids[j]].includes(g.home_id)&&shared.includes(g.away_id))||
            ([ids[i],ids[j]].includes(g.away_id)&&shared.includes(g.home_id)))).map(g=>g.id);
        }
      }
      if(w==null)continue;
      const probability=p[l][w]<spec[type],position=Math.abs(ranks.get(w)-ranks.get(l))<=spec.proximity;
      decision(w,l,type,{eligible:probability||position,qualification:probability&&position?'both':probability?'probability':position?'proximity':'neither',
        threshold:spec[type],proximity:spec.proximity,...meta});
    }
    const solver=typeof module!=='undefined'&&module.exports?require('./cfb-exact-order.js'):global.CFBExactOrder;
    const dynamicTrace=[];let solved,iteration=0;
    // Only pending comparisons can be added: a finite, monotone fixed point.
    while(true) {
      solved=await solver.solve(raw.map(i=>ids[i]),requirements,loadHighs,solverOptions.subsetLimit??18);
      const current=new Map(solved.order.map((i,k)=>[ids[raw[i]],k+1]));
      iteration++;let added=0;
      for(const row of audit) {
        if(row.eligible)continue;
        const w=row.winner_id,l=row.loser_id,gap=Math.abs(current.get(w)-current.get(l));
        if(gap>spec.proximity)continue;
        Object.assign(row,{eligible:true,qualification:`proximity_iteration_${iteration}`,admission_iteration:iteration,
          winner_rank_at_admission:current.get(w),loser_rank_at_admission:current.get(l),rank_gap_at_admission:gap});
        requirements.push({before:row.winner_raw_rank-1,after:row.loser_raw_rank-1,priority:row.priority});
        dynamicTrace.push({iteration,type:row.type,winner_id:w,loser_id:l,winner_rank:current.get(w),loser_rank:current.get(l),
          rank_gap:gap,raw_rank_gap:row.raw_rank_gap,p_loser_higher_merit:row.p_loser_higher_merit});added++;
      }
      if(!added)break;
    }
    const order=solved.order.map(i=>raw[i]),positions=new Map(order.map((i,k)=>[ids[i],k+1]));
    audit.sort((a,b)=>a.priority-b.priority||a.winner_id-b.winner_id||a.loser_id-b.loser_id);
    const graph=new Map([...positions.keys()].map(id=>[id,new Map()]));
    for(const row of audit) {
      row.winner_rank=positions.get(row.winner_id);row.loser_rank=positions.get(row.loser_id);row.final_order_respected=row.winner_rank<row.loser_rank;
      row.status=!row.eligible?'not_eligible':row.final_order_respected?'accepted':'overridden_by_global_objective';
      if(row.eligible&&row.final_order_respected&&!graph.get(row.winner_id).has(row.loser_id))graph.get(row.winner_id).set(row.loser_id,row.type);
    }
    for(const row of audit)if(row.status==='overridden_by_global_objective') {
      const start=row.loser_id,end=row.winner_id;let parents;
      for(let ceiling=1;ceiling<4;ceiling++) {
        parents=new Map([[start,null]]);const queue=[start];
        for(let k=0;k<queue.length&&!parents.has(end);k++) {
          const a=queue[k];for(const b of [...graph.get(a).keys()].sort((a,b)=>a-b))if(!parents.has(b)&&priorities[graph.get(a).get(b)]<=ceiling){parents.set(b,a);queue.push(b);}
        }
        if(parents.has(end))break;
      }
      const chain=[];if(parents.has(end)){let a=end;while(a!=null){chain.push(a);a=parents.get(a);}chain.reverse();}
      row.conflict_path=chain;row.conflict_requirements=chain.slice(0,-1).map((a,k)=>({winner_id:a,loser_id:chain[k+1],type:graph.get(a).get(chain[k+1])}));
      row.resolution='Global lexicographic optimum: direct results, common opponents, merit protection, raw inversions, stable IDs.';
    }
    return {specification:spec,order:order.map(i=>ids[i]),raw_order:raw.map(i=>ids[i]),unranked:ids.filter(id=>!positions.has(id)).sort((a,b)=>a-b),
      confidence_lock_count:audit.filter(r=>r.type==='merit_protection').length,audit,optimization:solved.optimization,dynamic_trace:dynamicTrace};
  }
  const api={run,defaults};if(typeof module!=='undefined'&&module.exports)module.exports=api;else global.CFBPolicyV5=api;
})(globalThis);
