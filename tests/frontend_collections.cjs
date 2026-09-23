const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
// Exercise the real fetch/normalization boundary without starting the router.
const core = source.slice(0, source.indexOf('async function hydrateOptionalSession'));
let payload;
let ok = true;
const context = vm.createContext({document: {getElementById: () => null},
  URL, fetch: async () => ({ok, status: 503, json: async () => payload})});
vm.runInContext(core, context);
const contracts = [
  ['/api/public/plans', ['plans', 'credit_packs']],
  ['/api/dashboard', ['series']],
  ['/api/usage?limit=8', ['events']],
  ['/api/usage/intelligence?window=30d', ['recent_runs', 'recent_failures', 'series']],
  ['/api/api-keys', ['keys']], ['/api/monitors', ['monitors']],
  ['/api/monitors/example/history?limit=25', ['runs']],
  ['/api/wallet?limit=150', ['ledger']],
  ['/api/billing/payments', ['payments']], ['/api/account/sessions', ['sessions']],
];
(async () => {
  for (const [url, fields] of contracts) {
    for (const value of [undefined, null, []]) {
      payload = Object.fromEntries(fields.map(key => [key, value]));
      const result = await context.api(url);
      for (const field of fields) assert.equal(Array.isArray(result[field]), true, `${url}: ${field}`);
    }
    for (const value of [{}, 'invalid', 1, false]) {
      payload = {[fields[0]]: value};
      await assert.rejects(context.api(url), /Expected an array/);
    }
    payload = null;
    await assert.rejects(context.api(url), /Expected an object/);
  }
  for (const breakdowns of [undefined, null, {status: null, tool: null, provider: null}]) {
    payload = {breakdowns};
    const result = await context.api('/api/usage/intelligence');
    for (const key of ['status', 'tool', 'provider']) assert.equal(result.breakdowns[key].length, 0);
  }
  payload = {keys: [{id: 'key1', scopes: null}, {id: 'key2'}]};
  assert.equal((await context.api('/api/api-keys')).keys[1].scopes.length, 0);
  payload = {events: [{request_id: 'real', credits_charged: 7}], next: 'cursor'};
  const result = await context.api('/api/usage');
  assert.equal(result.events[0].request_id, 'real');
  assert.equal(result.events[0].credits_charged, 7);
  assert.equal(result.next, 'cursor');
  assert.equal(result.events, payload.events);
  payload = {events: [null]};
  await assert.rejects(context.api('/api/usage'), /Expected an object/);
  payload = {breakdowns: {tool: 'invalid'}};
  await assert.rejects(context.api('/api/usage/intelligence'), /breakdowns.tool/);
  payload = {secret: 'fixture-only', scopes: null};
  assert.equal(await context.api('/api/api-keys', {method: 'POST'}), payload);
  payload = {run: {metadata: {events: null}}};
  assert.equal(await context.api('/api/usage/runs/fixture'), payload);
  ok = false; payload = {detail: 'Service unavailable'};
  await assert.rejects(context.api('/api/usage'), /Service unavailable/);
  // The original crash was a singular DOM query, independent of API data.
  const bindings = source.slice(source.indexOf('function bindCommon()'), source.indexOf('function codeBlock'));
  const buttons = [{dataset: {copy: 'first'}}, {dataset: {copy: 'second'}}];
  let controls = [];
  let copied;
  const dom = vm.createContext({$: () => null, $$: () => controls, copyText: value => {copied = value;}});
  vm.runInContext(bindings, dom);
  dom.bindCommon();
  controls = buttons; dom.bindCommon();
  buttons[1].onclick(); assert.equal(copied, 'second');
  console.log('Collection contracts and zero/multiple copy-control bindings passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
