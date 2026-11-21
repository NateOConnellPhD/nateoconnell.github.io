'use strict';
const revision=new URL(self.location.href).search;
importScripts('cfb-exact-order.js'+revision,'cfb-policy-v5.js'+revision);
let optimizer;
async function loadOptimizer() {
  if(!optimizer) {
    // A pinned, lazy dependency; normal small-block exploration needs no WASM.
    // No API credentials, cloud solver or HMC. Do not use an unversioned URL.
    const base='https://cdn.jsdelivr.net/npm/highs@1.16.0/build/';
    importScripts(base+'highs.js');
    optimizer=await Module({locateFile:name=>base+name});
  }
  return optimizer;
}
self.onmessage=async event=>{
  try {self.postMessage({result:await CFBPolicyV5.run(event.data.input,event.data.settings,loadOptimizer)});}
  catch(error){self.postMessage({error:error.message});}
};
