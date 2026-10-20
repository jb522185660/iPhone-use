import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { transform } from 'esbuild';

const source = await readFile(new URL('../src/browser.ts', import.meta.url), 'utf8');
const { code } = await transform(source.replace('export class BrowserApp', 'globalThis.BrowserApp = class BrowserApp'), { loader: 'ts', target: 'es2022' });
function harness(fetch) {
  const context = { window: { location: { href: 'http://127.0.0.1:18101/test-token/' } },
    URL, AbortController, setTimeout, clearTimeout, fetch };
  vm.runInNewContext(code, context);
  return new context.BrowserApp();
}

test('connects to its own local service without an MCP host handshake', async () => {
  const calls = [];
  const app = harness(async (...args) => { calls.push(args); return { ok: true, json: async () => ({ app: 'iphone-use-browser' }) }; });
  await app.connect();
  assert.equal(calls[0][0], '/test-token/health');
  assert.equal(app.getHostContext().displayMode, 'fullscreen');
  assert.equal(app.getHostContext().availableDisplayModes.length, 0);
});

test('preserves the frame and action contracts, token, timeout and no-cache behavior', async () => {
  const calls = [];
  const app = harness(async (...args) => { calls.push(args); return { ok: true, json: async () => ({ structuredContent: { frame_available: false } }) }; });
  const request = { name: 'pua_screen_action', arguments: { action: 'tap', x: 20, y: 30, width: 390, height: 844 } };
  const result = await app.callServerTool(request, { timeout: 1000 });
  assert.equal(calls[0][0], '/test-token/api');
  assert.equal(calls[0][1].method, 'POST');
  assert.equal(calls[0][1].headers.Authorization, 'Bearer test-token');
  assert.equal(calls[0][1].headers['Content-Type'], 'application/json');
  assert.equal(calls[0][1].cache, 'no-store');
  assert.deepEqual(JSON.parse(calls[0][1].body), request);
  assert.equal(result.structuredContent.frame_available, false);
});

test('HTTP rejection is not retried and a timed-out action is never replayed', async () => {
  let calls = 0;
  const rejected = harness(async () => { calls++; return { ok: false }; });
  await assert.rejects(rejected.callServerTool({ name: 'pua_screen_action' }));
  assert.equal(calls, 1);
  const timedOut = harness((url, { signal }) => { calls++; return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))); });
  await assert.rejects(timedOut.callServerTool({ name: 'pua_screen_action' }, { timeout: 5 }));
  assert.equal(calls, 2);
});

test('wrong service identity cannot silently become a connected phone panel', async () => {
  const app = harness(async () => ({ ok: true, json: async () => ({ app: 'other-service' }) }));
  await assert.rejects(app.connect());
});

test('a stalled health handshake times out so the shared renderer can reconnect', async () => {
  let calls = 0;
  const app = harness((url, { signal }) => {
    calls++;
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))));
  });
  await assert.rejects(app.connect(undefined, { timeout: 5 }));
  assert.equal(calls, 1);
});
