/* Exact lexicographic ordering. Small intervals use subset DP. Large intervals
 * use sequential integer programs, never a weighted penalty or an incumbent. */
((global) => {
  'use strict';
  const greater = (a,b) => {for(let k=0;k<a.length;k++) if(a[k]!==b[k]) return a[k]>b[k]; return false;};
  const popcount = v => {v-= (v>>>1)&0x55555555; v=(v&0x33333333)+((v>>>2)&0x33333333); return (((v+(v>>>4))&0x0F0F0F0F)*0x01010101)>>>24;};
  function blocks(n, rows) {
    const end=Array.from({length:n},(_,i)=>i), result=[];
    for(const r of rows) if(r.before>r.after) end[r.after]=Math.max(end[r.after],r.before);
    for(let start=0;start<n;) {
      let last=end[start]; for(let i=start;i<=last;i++) last=Math.max(last,end[i]);
      result.push(Array.from({length:last-start+1},(_,i)=>start+i)); start=last+1;
    }
    return result;
  }
  function subset(ids, rows) {
    const n=ids.length, size=2**n, preds=new Uint32Array(n), masks=Array.from({length:n},()=>new Uint32Array(4));
    for(const r of rows) {if(!r.priority) preds[r.after]|=1<<r.before; else masks[r.before][r.priority-1]|=1<<r.after;}
    for(let a=0;a<n;a++) for(let b=a+1;b<n;b++) masks[a][3]|=1<<b;
    const order=Array.from({length:n},(_,i)=>i).sort((a,b)=>ids[a]-ids[b]);
    const values=Array.from({length:4},()=>new Int32Array(size));
    const choices=new Int16Array(size).fill(-1); choices[0]=0;
    for(let remaining=1;remaining<size;remaining++) {
      let best=null;
      for(const a of order) {
        if(!(remaining&(1<<a)) || (preds[a]&remaining)) continue;
        const rest=remaining^(1<<a); if(choices[rest]<0) continue;
        const candidate=masks[a].map((mask,k)=>values[k][rest]+popcount(mask&rest));
        if(!best || greater(candidate,best)) {best=candidate; choices[remaining]=a;}
      }
      if(best) best.forEach((v,k)=>{values[k][remaining]=v;});
    }
    if(choices[size-1]<0) throw Error('Inconsistent hard ranking requirements.');
    const answer=[]; for(let rest=size-1;rest;) {const a=choices[rest];answer.push(a);rest^=1<<a;} return answer;
  }
  function integer(ids, rows, highs, deadline) {
    const n=ids.length, pairs=[], cols=new Map();
    for(let a=0;a<n;a++) for(let b=a+1;b<n;b++){cols.set(`${a},${b}`,pairs.length);pairs.push([a,b]);}
    const m=pairs.length, lower=Array(m).fill(0), upper=Array(m).fill(1), constraints=[];
    const targets=Array.from({length:4},(_,k)=>Array(m).fill(k===3?1:0));
    const dir=(a,b)=>[cols.get(`${Math.min(a,b)},${Math.max(a,b)}`),a<b?1:-1];
    for(const r of rows) {
      const [c,sign]=dir(r.before,r.after);
      if(!r.priority) {const value=Number(sign===1);if(lower[c]===upper[c]&&lower[c]!==value) throw Error('Inconsistent hard ranking requirements.');lower[c]=upper[c]=value;}
      else targets[r.priority-1][c]+=sign;
    }
    for(let a=0;a<n;a++)for(let b=a+1;b<n;b++)for(let c=b+1;c<n;c++) {
      const terms=[[cols.get(`${a},${b}`),1],[cols.get(`${b},${c}`),1],[cols.get(`${a},${c}`),-1]];
      constraints.push([terms,'>=',0],[terms,'<=',1]);
    }
    const expression=terms=>terms.map(([i,c])=>`${c<0?'-':'+'} ${Math.abs(c)} x${i}`).join(' ')||'+ 0 x0';
    const nonzero=target=>target.map((c,i)=>[i,c]).filter(([,c])=>c);
    function optimize(target,extra=[]) {
      const left=(deadline-Date.now())/1000;
      if(left<=0) throw Error('Exact optimization reached its time limit. No approximate ranking was used.');
      const width=target.length, names=Array.from({length:width},(_,i)=>`x${i}`);
      const lp=['Maximize',` obj: ${expression(nonzero(target))}`,'Subject To',
        ...constraints.concat(extra).map(([terms,op,b],i)=>` c${i}: ${expression(terms)} ${op} ${b}`),'Bounds',
        ...names.map((name,i)=>` ${i<m?lower[i]:0} <= ${name} <= ${i<m?upper[i]:1}`),'Binary',names.join(' '),'End'].join('\n');
      const r=highs.solve(lp,{output_flag:false,mip_rel_gap:0,mip_abs_gap:0,time_limit:left,threads:1});
      if(r.Status!=='Optimal') throw Error('Exact optimization did not prove an optimum. No approximate ranking was used.');
      const solution=names.map(name=>r.Columns[name].Primal);
      if(solution.some(v=>!Number.isFinite(v)||Math.abs(v-Math.round(v))>1e-6)) throw Error('Noninteger solver result.');
      const rounded=solution.map(Math.round);
      for(const [terms,op,b] of constraints.concat(extra)) {
        const v=terms.reduce((sum,[i,c])=>sum+c*rounded[i],0);
        if((op==='='&&v!==b)||(op==='<='&&v>b)||(op==='>='&&v<b)) throw Error('Solver constraint check failed.');
      }
      return rounded;
    }
    for(const target of targets) if(target.some(Boolean)) {
      const s=optimize(target), value=target.reduce((sum,c,i)=>sum+c*s[i],0);
      constraints.push([nonzero(target),'=',value]);
    }
    const result=[], remaining=new Set(ids.map((_,i)=>i)), stable=[...remaining].sort((a,b)=>ids[a]-ids[b]);
    while(remaining.size>1) {
      const candidates=[...remaining], z=new Map(candidates.map((a,k)=>[a,m+k]));
      const extra=[[[...z.values()].map(c=>[c,1]),'=',1]], target=Array(m+candidates.length).fill(0);
      for(const a of candidates) {
        target[z.get(a)]=-stable.indexOf(a);
        for(const b of candidates) if(a!==b) {const [c,sign]=dir(a,b);extra.push([[[z.get(a),1],[c,-sign]],'<=',sign===1?0:1]);}
      }
      const s=optimize(target,extra), first=candidates.filter(a=>s[z.get(a)]===1);
      if(first.length!==1) throw Error('Invalid stable-ID tie-break.');
      const a=first[0];result.push(a);remaining.delete(a);
      for(const b of remaining) {const [c,sign]=dir(a,b);lower[c]=upper[c]=Number(sign===1);}
    }
    return result.concat([...remaining]);
  }
  async function solve(ids, rows, loadHighs, subsetLimit=18) {
    const result=[], methods=[], deadline=Date.now()+120000;
    let highs;
    for(const group of blocks(ids.length,rows)) {
      const map=new Map(group.map((a,i)=>[a,i]));
      const local=rows.filter(r=>map.has(r.before)&&map.has(r.after)).map(r=>({...r,before:map.get(r.before),after:map.get(r.after)}));
      const keys=group.map(i=>ids[i]); let chosen, method;
      if(group.length<=subsetLimit) {chosen=subset(keys,local);method='subset_dynamic_programming';}
      else {
        if(!loadHighs) throw Error('The exact optimizer is unavailable. Official rankings remain available.');
        highs ||= await loadHighs(); chosen=integer(keys,local,highs,deadline);method='lexicographic_integer_optimization';
      }
      result.push(...chosen.map(i=>group[i]));methods.push({size:group.length,method});
    }
    const positions=new Map(result.map((a,i)=>[a,i])), counts=[0,0,0];
    for(const r of rows) {
      const respected=positions.get(r.before)<positions.get(r.after);
      if(!r.priority&&!respected) throw Error('Hard ranking requirement violated.');
      if(r.priority&&respected) counts[r.priority-1]++;
    }
    let inversions=0;for(let a=0;a<result.length;a++)for(let b=a+1;b<result.length;b++) inversions+=Number(result[a]>result[b]);
    return {order:result,optimization:{optimal:true,head_to_head:counts[0],common_opponents:counts[1],merit_protection:counts[2],
      raw_inversions:inversions,tie_break:'Lexicographically smallest stable-ID sequence',blocks:methods}};
  }
  const api={solve,subset,integer,blocks};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else global.CFBExactOrder=api;
})(globalThis);
