/* Offline function parity, not a browser/UI test. */
const fs=require('node:fs');
const policy=require('../../assets/js/cfb-policy-v5.js');
(async()=>{
  const cases=JSON.parse(fs.readFileSync(0,'utf8')),results=[];
  for(const c of cases) results.push(await policy.run(c.input,c.settings));
  process.stdout.write(JSON.stringify(results));
})().catch(error=>{console.error(error.message);process.exitCode=1;});
