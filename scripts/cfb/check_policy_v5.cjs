/* Offline function parity, not a browser/UI test. */
const fs=require('node:fs');
const assert=require('node:assert/strict');
const policy=require('../../assets/js/cfb-policy-v5.js');
(async()=>{
  const cases=JSON.parse(fs.readFileSync(0,'utf8')),results=[];
  for(const c of cases) results.push(await policy.run(c.input,c.settings));
  if(cases.length) await assert.rejects(policy.run(cases[0].input,
    {...cases[0].settings,undefeated_p4_protection:true}), /Unrecognized policy setting/);
  process.stdout.write(JSON.stringify(results));
})().catch(error=>{console.error(error.message);process.exitCode=1;});
