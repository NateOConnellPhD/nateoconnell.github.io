/* Keep policy work off the page thread. Every season uses the current rules. */
((global)=>{
  'use strict';
  const script=typeof document==='undefined'?null:document.currentScript?.src;
  const workerURL=script?new URL('cfb-policy-worker.js'+new URL(script).search,script):null;
  const cache=new Map(),inputs=new WeakMap();let serial=0,worker=null,pending=null;
  function cancel() {
    worker?.terminate();worker=null;
    if(pending){clearTimeout(pending.timer);pending.reject(Object.assign(Error('Superseded ranking request'),{name:'AbortError'}));pending=null;}
  }
  async function run(input,settings) {
    if(input?.schema!=='margin-of-merit-policy-input-v5')throw Error('This week is awaiting a refit under the current model and rules.');
    if(!inputs.has(input))inputs.set(input,++serial);
    const key=JSON.stringify([inputs.get(input),settings]);
    if(cache.has(key))return cache.get(key);
    cancel();
    if(!workerURL||typeof Worker==='undefined')throw Error('This browser cannot run the ranking explorer. Saved official rankings are still available.');
    worker=new Worker(workerURL);
    return new Promise((resolve,reject)=>{
      pending={resolve,reject};
      const active=worker;
      const timer=setTimeout(()=>{if(worker===active){finish();reject(Error('The exact ranking calculation timed out. Official rankings are preserved.'));}},150000);
      pending.timer=timer;
      const finish=()=>{clearTimeout(timer);active.terminate();if(worker===active){worker=null;pending=null;}};
      worker.onmessage=event=>{
        if(worker!==active){clearTimeout(timer);return;}
        const {result,error}=event.data;finish();
        if(error){reject(Error(error));return;}
        cache.set(key,result);while(cache.size>6)cache.delete(cache.keys().next().value);resolve(result);
      };
      worker.onerror=()=>{if(worker!==active){clearTimeout(timer);return;}finish();reject(Error('The ranking worker could not finish. The official rankings are preserved.'));};
      worker.postMessage({input,settings});
    });
  }
  const api={run,cancel};if(typeof module!=='undefined'&&module.exports)module.exports=api;else global.CFBPolicy=api;
})(globalThis);
