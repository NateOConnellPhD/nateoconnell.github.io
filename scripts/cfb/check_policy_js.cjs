// Offline parity runner, not a browser test. Reads fixtures from stdin only.
const fs = require('node:fs');
const policy = require('../../assets/js/cfb-policy.js');
const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(({input, settings}) => {
  try { return policy.run(input, settings); }
  catch (error) {
    if (!error.decision) throw error;
    return {error: true, decision: error.decision, audit: error.audit};
  }
})));
