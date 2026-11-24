// Name resolution only: no DOM, browser, network, model calls, or output files.
const assert=require('node:assert/strict');
const {quarterbackName}=require('../../assets/js/cfb-projections.js');
for(const value of [undefined,null,5161854,'5161854','5161854.0','5.161854e6','Passer 5161854','unknown',''])
  assert.equal(quarterbackName(value,'5161854'),null);
const names={'101':'Roster Quarterback','102':'New Backup'};
assert.equal(quarterbackName('101','101',names),'Roster Quarterback');
assert.equal(quarterbackName(null,102,names),'New Backup');
assert.equal(quarterbackName('Saved Name','103',names),'Saved Name');
assert.equal(quarterbackName('Saved Name','103',{'103':'103'}),'Saved Name');
assert.equal(quarterbackName('  D’Andre   Smith II ','104'),'D’Andre Smith II');
console.log('QB name resolution checks passed');
