import test from 'node:test';
import assert from 'node:assert/strict';

// Exercise the diagnostic's request and cleanup paths without a live API key.
for (const scenario of ['completed', 'failed', 'submission-rejected']) {
  test(`standalone diagnostic: ${scenario}`, async () => {
    const original = { fetch, log: console.log, key: process.env.OPENAI_API_KEY, model: process.env.OPENAI_AGENT_MODEL, exitCode: process.exitCode, argv: process.argv };
    const logs = [], calls = [];
    try {
      process.env.OPENAI_API_KEY = 'sk-test-secret'; delete process.env.OPENAI_AGENT_MODEL;
      process.argv = ['node', 'check-agent.mjs'];
      console.log = value => logs.push(value);
      globalThis.fetch = async (url, options) => {
        const body = options.body && JSON.parse(options.body); calls.push({ url, method: options.method, body });
        if (url.endsWith('/sessions')) {
          assert.deepEqual(body.environment, { type: 'none' });
          assert.equal(body.input, undefined);
          assert.equal(JSON.stringify(body).includes('sk-test-secret'), false);
          return Response.json({ id: 'sess_probe' });
        }
        if (options.method === 'DELETE') return new Response(null, { status: 204 });
        if (options.method === 'POST') {
          if (scenario === 'submission-rejected') return Response.json({ error: { code: 'forbidden', message: 'Denied sk-test-secret' } }, { status: 403 });
          return new Response(null, { status: 202 });
        }
        const event = scenario === 'failed'
          ? { type: 'agent.session.turn.failed', turn: { id: 'turn_probe', error: { code: 'internal_error', message: 'An internal error occurred.' } } }
          : { type: 'agent.session.turn.completed', turn: { id: 'turn_probe' } };
        return new Response(`data: ${JSON.stringify(event)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } });
      };
      await import(`../scripts/check-agent.mjs?case=${scenario}`);
      assert.equal(process.exitCode, scenario === 'completed' ? 0 : 1);
      assert.equal(calls.filter(call => call.body?.events?.[0].type === 'agent.session.input.message').length, 1);
      assert.equal(calls.at(-1).method, 'DELETE');
      assert.equal(logs.join('\n').includes('sk-test-secret'), false);
      assert.ok(logs.some(value => value.includes('Diagnostic session deleted.')));
      if (scenario === 'failed') assert.ok(logs.some(value => value.includes('internal_error') && value.includes('turn_probe')));
    } finally {
      globalThis.fetch = original.fetch; console.log = original.log; process.exitCode = original.exitCode; process.argv = original.argv;
      for (const [name, value] of [['OPENAI_API_KEY', original.key], ['OPENAI_AGENT_MODEL', original.model]]) {
        if (value === undefined) delete process.env[name]; else process.env[name] = value;
      }
    }
  });
}
