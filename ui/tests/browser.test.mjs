import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { transform } from 'esbuild';

const source = await readFile(new URL('../src/browser.ts', import.meta.url), 'utf8');
const { code } = await transform(source.replace('export class BrowserApp', 'globalThis.BrowserApp = class BrowserApp'), { loader: 'ts', target: 'es2022' });
function harness(fetch) {
  const context = { window: { location: { href: 'http://127.0.0.1:18101/' } },
    URL, AbortController, setTimeout, clearTimeout, fetch };
  vm.runInNewContext(code, context);
  return new context.BrowserApp();
}

test('connects to its own local service without an MCP host handshake', async () => {
  const calls = [];
  const app = harness(async (...args) => { calls.push(args); return { ok: true, json: async () => ({ app: 'iphone-use-browser', token: 'session-token' }) }; });
  await app.connect();
  assert.equal(calls[0][0], '/session');
  assert.equal(calls[0][1].headers['X-iPhone-Use'], 'browser');
  assert.equal(app.getHostContext().displayMode, 'fullscreen');
  assert.equal(app.getHostContext().availableDisplayModes.length, 0);
});

test('preserves the frame and action contracts, token, timeout and no-cache behavior', async () => {
  const calls = [];
  const app = harness(async (...args) => { calls.push(args); return { ok: true, json: async () => args[0] === '/session'
    ? { app: 'iphone-use-browser', token: 'session-token' } : { structuredContent: { frame_available: false } } }; });
  const request = { name: 'pua_screen_action', arguments: { action: 'tap', x: 20, y: 30, width: 390, height: 844 } };
  const result = await app.callServerTool(request, { timeout: 1000 });
  assert.equal(calls.length, 2);
  assert.equal(calls[1][0], '/api');
  assert.equal(calls[1][1].method, 'POST');
  assert.equal(calls[1][1].headers.Authorization, 'Bearer session-token');
  assert.equal(calls[1][1].headers['Content-Type'], 'application/json');
  assert.equal(calls[1][1].cache, 'no-store');
  assert.deepEqual(JSON.parse(calls[1][1].body), request);
  assert.equal(result.structuredContent.frame_available, false);
});

test('HTTP rejection is not retried and a timed-out action is never replayed', async () => {
  let calls = 0;
  const session = { ok: true, json: async () => ({ app: 'iphone-use-browser', token: 'session-token' }) };
  const rejected = harness(async path => { if (path === '/session') return session; calls++; return { ok: false, status: 500 }; });
  await assert.rejects(rejected.callServerTool({ name: 'pua_screen_action' }));
  assert.equal(calls, 1);
  const timedOut = harness((url, { signal }) => { if (url === '/session') return Promise.resolve(session); calls++; return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))); });
  await assert.rejects(timedOut.callServerTool({ name: 'pua_screen_action' }, { timeout: 5 }));
  assert.equal(calls, 2);
});

test('wrong service identity and missing credentials cannot become a connected phone panel', async () => {
  for (const data of [{ app: 'other-service', token: 'other' }, { app: 'iphone-use-browser' }, { app: 'iphone-use-browser', token: '' }]) {
    const app = harness(async () => ({ ok: true, json: async () => data }));
    await assert.rejects(app.connect());
  }
});

test('a stalled session handshake times out so the shared renderer can reconnect', async () => {
  let calls = 0;
  const app = harness((url, { signal }) => {
    calls++;
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))));
  });
  await assert.rejects(app.connect(undefined, { timeout: 5 }));
  assert.equal(calls, 1);
});

test('worker restart renews credentials at the same address without replaying a rejected action', async () => {
  const calls = [];
  let token = 'first';
  const app = harness(async (path, options) => {
    calls.push({ path, options });
    if (path === '/session') return { ok: true, json: async () => ({ app: 'iphone-use-browser', token }) };
    const ok = options.headers.Authorization === 'Bearer ' + token;
    return { ok, status: ok ? 200 : 403, json: async () => ({ structuredContent: { frame_available: false } }) };
  });
  await app.callServerTool({ name: 'pua_screen_frame' });
  token = 'second';
  await assert.rejects(app.callServerTool({ name: 'pua_screen_action', arguments: { action: 'home' } }));
  assert.equal(calls.length, 3);
  await app.callServerTool({ name: 'pua_screen_frame' });
  assert.deepEqual(calls.map(call => call.path), ['/session', '/api', '/api', '/session', '/api']);
  assert.equal(calls.at(-1).options.headers.Authorization, 'Bearer second');
  assert.equal(calls.filter(call => call.options.body && JSON.parse(call.options.body).name === 'pua_screen_action').length, 1);
});

test('simultaneous connects and first frame requests share a single session bootstrap', async () => {
  let sessions = 0;
  const app = harness(async path => {
    if (path === '/session') { sessions++; return { ok: true, json: async () => ({ app: 'iphone-use-browser', token: 'shared' }) }; }
    return { ok: true, json: async () => ({ structuredContent: {} }) };
  });
  await Promise.all([app.connect(), app.connect(), app.callServerTool({ name: 'pua_screen_frame' })]);
  assert.equal(sessions, 1);
});
