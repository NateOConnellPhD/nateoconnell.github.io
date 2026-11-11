import test from 'node:test';
import assert from 'node:assert/strict';

// Exercise the diagnostic's request and cleanup paths without a live API key.
for (const scenario of ['completed', 'hosted-completed', 'failed', 'stream-interrupted', 'creation-uncertain', 'creation-unauthorized', 'creation-invalid']) {
  test(`standalone diagnostic: ${scenario}`, async () => {
    const original = { fetch, log: console.log, key: process.env.OPENAI_API_KEY, model: process.env.OPENAI_AGENT_MODEL, exitCode: process.exitCode, argv: process.argv };
    const logs = [], calls = [];
    const success = ['completed', 'hosted-completed'].includes(scenario);
    const rejected = ['creation-unauthorized', 'creation-invalid'].includes(scenario);
    let diagnosticId;
    try {
      process.env.OPENAI_API_KEY = 'sk-test-secret'; delete process.env.OPENAI_AGENT_MODEL;
      process.argv = ['node', 'check-agent.mjs', ...(scenario === 'hosted-completed' ? ['--hosted'] : [])];
      console.log = value => logs.push(value);
      globalThis.fetch = async (url, options) => {
        const body = options.body && JSON.parse(options.body); calls.push({ url, method: options.method, body });
        if (url.endsWith('/sessions')) {
          assert.equal(options.method, 'POST');
          assert.deepEqual(body.environment, { type: scenario === 'hosted-completed' ? 'openai_hosted' : 'none' });
          assert.equal(body.input, 'Reply with exactly the word connected.');
          assert.equal(body.stream, true, 'The first reply must be streamed in the same request that submits input.');
          assert.equal(JSON.stringify(body).includes('sk-test-secret'), false);
          diagnosticId = body.metadata.editor_diagnostic;
          if (scenario === 'creation-uncertain') throw new TypeError('fetch failed');
          if (scenario === 'creation-unauthorized') return Response.json({ error: { message: 'A valid actor biscuit is required.' } }, { status: 401 });
          if (scenario === 'creation-invalid') return Response.json({ error: { code: 'invalid_request_error', message: 'conversation-only sessions currently require initial input' } }, { status: 400 });
          const events = [{ type: 'agent.session.created', session: { id: 'sess_probe' } }];
          if (success) events.push(
            { type: 'agent.session.turn.output_text.done', session_id: 'sess_probe', text: 'connected' },
            { type: 'agent.session.turn.completed', session_id: 'sess_probe', turn: { id: 'turn_probe' } }
          );
          if (scenario === 'failed') events.push({ type: 'agent.session.turn.failed', session_id: 'sess_probe', turn: { id: 'turn_probe', error: { code: 'internal_error', message: 'An internal error occurred.' } } });
          // Deliver all events immediately: there must be no later subscription
          // that could miss the already-completed reply.
          return new Response(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(''), { headers: { 'Content-Type': 'text/event-stream' } });
        }
        if (options.method === 'GET' && scenario === 'creation-uncertain') {
          assert.equal(new URL(url).searchParams.get('metadata[editor_diagnostic]'), diagnosticId);
          return Response.json({ data: [{ id: 'sess_probe', metadata: { editor_diagnostic: diagnosticId } }] });
        }
        if (options.method === 'DELETE') {
          assert.ok(url.endsWith('/sessions/sess_probe'));
          return new Response(null, { status: 204 });
        }
        assert.equal(body.events[0].type, 'agent.session.input.cancel', 'Never submit the initial message a second time.');
        return Response.json({ error: { code: 'forbidden', message: 'Denied sk-test-secret' } }, { status: 403 });
      };
      await import(`../scripts/check-agent.mjs?case=${scenario}`);
      assert.equal(process.exitCode, success ? 0 : 1);
      assert.equal(calls.filter(call => call.body?.input).length, 1);
      if (rejected) {
        assert.equal(calls.length, 1, 'An explicit creation rejection must not trigger session recovery or another request.');
        assert.ok(logs.some(value => value.includes('No diagnostic session was created.')));
        return;
      }
      assert.equal(calls.filter(call => call.body?.events?.[0].type === 'agent.session.input.message').length, 0);
      assert.equal(calls.at(-1).method, 'DELETE');
      assert.equal(logs.join('\n').includes('sk-test-secret'), false);
      assert.ok(logs.some(value => value.includes('Diagnostic session deleted.')));
      if (success) assert.ok(logs.some(value => value.includes('"reply":"connected"')));
      if (scenario === 'failed') assert.ok(logs.some(value => value.includes('internal_error') && value.includes('turn_probe')));
    } finally {
      globalThis.fetch = original.fetch; console.log = original.log; process.exitCode = original.exitCode; process.argv = original.argv;
      for (const [name, value] of [['OPENAI_API_KEY', original.key], ['OPENAI_AGENT_MODEL', original.model]]) {
        if (value === undefined) delete process.env[name]; else process.env[name] = value;
      }
    }
  });
}

for (const statuses of [[200, 200], [200, 401], [403, 200]]) {
  test(`authentication-only diagnostic: models ${statuses[0]}, agents ${statuses[1]}`, async () => {
    const original = { fetch, log: console.log, key: process.env.OPENAI_API_KEY, exitCode: process.exitCode, argv: process.argv };
    const logs = [], calls = [];
    try {
      process.env.OPENAI_API_KEY = 'sk-test-secret';
      // Auth-only must remain read-only even if --hosted is also supplied.
      process.argv = ['node', 'check-agent.mjs', '--auth-only', '--hosted'];
      console.log = value => logs.push(value);
      globalThis.fetch = async (url, options) => {
        calls.push(url);
        assert.equal(options.method, 'GET');
        assert.equal(options.body, undefined);
        assert.equal(options.redirect, 'error');
        assert.equal(options.headers.Authorization, 'Bearer sk-test-secret');
        assert.equal(options.headers['OpenAI-Beta'], calls.length === 1 ? undefined : 'agents=v1');
        const status = statuses[calls.length - 1];
        return Response.json(status === 200 ? { data: [{ id: 'private-account-data' }] } : { error: { message: 'Denied sk-test-secret' } }, { status, headers: { 'x-request-id': `req_probe_${calls.length}` } });
      };
      await import(`../scripts/check-agent.mjs?auth=${statuses.join('-')}`);
      assert.deepEqual(calls, ['https://api.openai.com/v1/models', 'https://api.openai.com/v1/agents/sessions?limit=1']);
      assert.equal(process.exitCode, statuses.every(status => status === 200) ? 0 : 1);
      assert.ok(logs.some(value => value.includes('req_probe_1')));
      assert.ok(logs.some(value => value.includes('req_probe_2')));
      assert.ok(logs.some(value => value.includes('"modelRequests":0')));
      assert.equal(logs.join('\n').includes('private-account-data'), false);
      assert.equal(logs.join('\n').includes('sk-test-secret'), false);
    } finally {
      globalThis.fetch = original.fetch; console.log = original.log; process.exitCode = original.exitCode; process.argv = original.argv;
      if (original.key === undefined) delete process.env.OPENAI_API_KEY; else process.env.OPENAI_API_KEY = original.key;
    }
  });
}
