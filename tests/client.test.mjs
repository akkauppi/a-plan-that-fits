import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SolverClient } from '../src/solver/client.ts';

function harness() {
  const workers = [], states = [];
  const client = new SolverClient({}, () => {
    const worker = { onmessage: null, onerror: null, messages: [], terminated: false,
      postMessage(message) { this.messages.push(message); }, terminate() { this.terminated = true; },
      emit(message) { this.onmessage({ data: message }); },
    };
    workers.push(worker); return worker;
  }, state => states.push(state));
  return { client, workers, states, latest: () => states.at(-1) };
}
test('request serialization, wrong-ID rejection, cancellation and stale-worker rejection', () => {
  const { client, workers, latest } = harness();
  try {
    const first = workers[0];
    assert.equal(client.solve({ timeoutMs: 15000 }), false);
    first.emit({ type: 'ready' });
    assert.equal(client.solve({ timeoutMs: 15000 }), true);
    assert.equal(client.solve({ timeoutMs: 15000 }), false);
    const id = first.messages.at(-1).requestId;
    first.emit({ type: 'result', requestId: id + 1, result: { status: 'unsat' } });
    assert.equal(latest().phase, 'solving');
    client.cancel();
    assert.equal(first.terminated, true);
    assert.equal(latest().result.status, 'cancelled');
    first.emit({ type: 'result', requestId: id, result: { status: 'feasible' } });
    assert.equal(latest().result.status, 'cancelled');
    const second = workers[1]; second.emit({ type: 'ready' });
    client.solve({ timeoutMs: 15000 });
    assert.ok(second.messages.at(-1).requestId > id);
    second.emit({ type: 'result', requestId: second.messages.at(-1).requestId, result: { status: 'unsat' } });
    assert.equal(latest().result.status, 'unsat');
  } finally { client.dispose(); }
});
test('worker crashes and watchdog expiry are errors/timeouts, never UNSAT', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { client, workers, latest } = harness();
  try {
    workers[0].emit({ type: 'ready' }); client.solve({ timeoutMs: 5 });
    t.mock.timers.tick(5006);
    assert.equal(latest().result.status, 'timeout');
    assert.equal(workers[0].terminated, true);
    workers[1].onerror({ message: 'WASM failed' });
    assert.equal(latest().phase, 'error');
    assert.equal(latest().result, undefined);
    assert.match(latest().message, /WASM failed/);
  } finally { client.dispose(); }
});
test('initialisation timeout does not leave the tour silently busy', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { client, workers, latest } = harness();
  try {
    t.mock.timers.tick(60001);
    assert.equal(latest().phase, 'error');
    assert.equal(workers[0].terminated, true);
  } finally { client.dispose(); }
});
