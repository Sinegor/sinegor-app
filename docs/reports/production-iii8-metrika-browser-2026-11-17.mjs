import { chromium } from '../../apps/web/node_modules/playwright/index.mjs';
import { writeFile } from 'node:fs/promises';

const origin = 'https://sinegor-lab.website';
const counter = 114298562;
const withdrawalOnly = process.argv.includes('--withdrawal-only');
const returnOnly = process.argv.includes('--return-only');
const output = new URL(returnOnly ? './production-iii8-metrika-return-evidence-2026-11-17.json' : withdrawalOnly ? './production-iii8-metrika-withdrawal-evidence-2026-11-17.json' : './production-iii8-metrika-browser-evidence-2026-11-17.json', import.meta.url);
const evidence = {
  observedAt: new Date().toISOString(), counterId: counter,
  isolatedProfile: true, realCounterNetwork: true,
  authenticatedPrivatePagesChecked: false,
  syntheticConsentRecordsAllowed: true,
  requests: [], consentAttempts: [], consentReceipts: [], observations: [], failures: [],
  tests: returnOnly ? { returnAfterPrivate: false } : withdrawalOnly ? { withdrawal: false } : { withoutConsent: false, afterConsent: false, privateRoutes: false, withdrawal: false },
  criticalFirstPartyNetworkFailures: [],
};
const analyticsHost = host => /(^|\.)(?:mc\.(?:yandex\.[a-z.]+|webvisor\.[a-z.]+|yango\.com)|yandexmetrica\.com)$/.test(host);
const privatePath = value => /\/(auth|customer|admin)(\/|\?|$)/i.test(value);
const markerPattern = /iii8_synthetic_(?:secret|order|fragment)|iii8-synthetic%40example\.invalid|iii8-synthetic@example\.invalid/i;
const safePublicPaths = new Set(['/', '/publications', '/documents', '/about', '/contacts']);
const requestRecords = new Map();
const starts = new Map();
const timings = [];
let phase = 'startup';
let lastGrantReceiptAt = 0;
let browser;
let context;
let page;

function assert(value, message) { if (!value) throw new Error(message); }
function decoded(text) {
  let result = text;
  for (let i = 0; i < 4; i++) {
    try { const next = decodeURIComponent(result.replace(/\+/g, ' ')); if (next === result) break; result = next; }
    catch { break; }
  }
  return result;
}
function analyticsRequests(since = 0) { return evidence.requests.filter(r => r.at >= since && r.analytics); }
function pageviews(path, since = 0) {
  return analyticsRequests(since).filter(r => r.pageview && !r.initializationWithoutHit && !r.redirectedFrom && r.publicPage === path && r.method !== 'OPTIONS');
}
async function state() {
  return page.evaluate(() => {
    let value;
    try { value = JSON.parse(localStorage.getItem('sinegor.analytics-consent.v1') || 'null'); } catch {}
    return {
      consent: value?.decision ?? null, pending: value?.pending?.event_type ?? null,
      metrikaScripts: [...document.scripts].filter(s => s.src === 'https://mc.yandex.ru/metrika/tag.js').length,
      vendorScriptElements: [...document.scripts].filter(s => /mc\.yandex\./.test(s.src)).length,
      heading: !!document.querySelector('h1'),
    };
  });
}
async function until(check, message, timeout = 20000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await check()) return; await page.waitForTimeout(200); }
  throw new Error(message);
}
async function observe(name, extra = {}) {
  evidence.observations.push({ scenario: name, at: Date.now(), ...await state(), ...extra });
}
async function openSettings() {
  await page.getByRole('button', { name: 'Настройки аналитики', exact: true }).click();
  await page.getByRole('dialog', { name: 'Настройки аналитики', exact: true }).waitFor({ state: 'visible' });
}
async function choose(decision) {
  const label = decision === 'accepted' ? 'Разрешить' : 'Отклонить';
  await page.getByRole('dialog').getByRole('button', { name: label, exact: true }).click();
  await until(async () => { const v = await state(); return v.consent === decision && !v.pending; }, 'consent_choice_not_committed');
}
async function navigation(action) {
  for (let attempt = 0; ; attempt++) {
    try { return await action(); }
    catch (error) {
      const code = String(error?.message).match(/net::ERR_(?:NETWORK_CHANGED|CONNECTION_CLOSED)/)?.[0];
      if (!code || attempt >= 2) throw error;
      (evidence.navigationTransportRecoveries ??= []).push({ phase, networkError: code, attempt: attempt + 1 });
      await page.waitForTimeout(1200);
    }
  }
}
async function safeReload() {
  return navigation(() => page.reload({ waitUntil: 'domcontentloaded', timeout: 35000 }));
}
async function goto(path) {
  const response = await navigation(() => page.goto(origin + path, { waitUntil: 'domcontentloaded', timeout: 35000 }));
  assert(response?.status() === 200, 'document_http_status');
  await page.locator('h1').waitFor({ state: 'visible', timeout: 15000 });
}

async function publicNavigation(label, path) {
  await page.getByRole('navigation', { name: 'Основная навигация', exact: true }).getByRole('link', { name: label, exact: true }).click();
  await page.waitForURL(origin + path);
  await until(() => pageviews(path).some(r => (r.deliveryStatus ?? r.responseStatus) >= 200 && (r.deliveryStatus ?? r.responseStatus) < 300), 'real_public_pageview_missing');
  await page.waitForTimeout(1800);
}

try {
  browser = await chromium.launch({ headless: true });
  evidence.browserVersion = browser.version();
  evidence.browserDistribution = 'Playwright bundled Chromium';
  context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 900 } });
  // Observe calls while forwarding every call/property to the real implementation.
  // No mock library, response replacement, cookies or identifiers are exported.
  await context.addInitScript(() => {
    const calls = [];
    Object.defineProperty(window, '__iii8ObservedMethods', { value: calls });
    let current;
    Object.defineProperty(window, 'ym', {
      configurable: true, enumerable: true,
      get() { return current; },
      set(value) {
        current = typeof value !== 'function' ? value : new Proxy(value, {
          apply(target, receiver, args) {
            if (typeof args[0] === 'number' && typeof args[1] === 'string') {
              const item = { at: Date.now(), counterId: args[0], method: args[1] };
              if (args[1] === 'init') item.options = Object.fromEntries(['defer', 'webvisor', 'clickmap', 'trackLinks', 'accurateTrackBounce', 'trackHash', 'sendTitle', 'disableYtm', 'ecommerce'].map(k => [k, args[2]?.[k]]));
              calls.push(item);
            }
            return Reflect.apply(target, receiver, args);
          },
        });
      },
    });
  });
  await context.route('**/*', async route => {
    const r = route.request(); const u = new URL(r.url());
    if (u.origin === origin && !['GET', 'HEAD', 'OPTIONS'].includes(r.method()) && !(u.pathname === '/api/analytics/consent' && r.method() === 'POST')) {
      evidence.failures.push('unexpected_same_origin_mutation_blocked');
      return route.abort();
    }
    return route.continue();
  });
  context.on('request', request => {
    const at = Date.now(); const u = new URL(request.url());
    starts.set(request, at);
    if (u.origin === origin) {
      if (u.pathname === '/api/analytics/consent' && request.method() === 'POST') {
        let kind = 'unknown'; try { kind = request.postDataJSON().event_type; } catch {}
        const attempt = { at, phase, eventType: ['grant', 'withdraw'].includes(kind) ? kind : 'unknown' }; evidence.consentAttempts.push(attempt); requestRecords.set(request, attempt);
      }
      return;
    }
    const analytics = analyticsHost(u.hostname) || u.origin !== origin;
    const prior = requestRecords.get(request.redirectedFrom());
    const item = {
      at, phase, host: u.hostname, method: request.method(), analytics,
      redirectedFrom: !!request.redirectedFrom(), redirectChain: prior?.redirectChain ?? evidence.requests.length + 1,
      endpoint: /\/metrika\/tag\.js/.test(u.pathname) ? 'tag.js' : /\/watch\//.test(u.pathname) ? 'watch' : 'other',
      counterMatches: u.pathname.includes(String(counter)) || u.searchParams.get('id') === String(counter),
      publicPage: null, pageview: false, goal: false, privateDataDetected: false,
    };
    if (analytics) {
      const body = request.postData() || '';
      const params = new URLSearchParams(u.search);
      const postParams = new URLSearchParams(body);
      for (const [k, v] of postParams) if (!params.has(k)) params.set(k, v);
      const pageUrl = params.get('page-url') || '';
      const browserInfo = params.get('browser-info') || '';
      item.parameterNames = [...new Set(params.keys())].sort();
      item.initializationWithoutHit = params.has('nohit') && params.get('nohit') !== '0';
      item.pageview = /(?:^|:)pv:1(?:$|:)/.test(browserInfo);
      item.goal = pageUrl.startsWith('goal://');
      try { const pu = new URL(pageUrl); if (pu.origin === origin && safePublicPaths.has(pu.pathname) && !pu.search && !pu.hash) item.publicPage = pu.pathname; } catch {}
      const data = decoded(request.url() + '\n' + body);
      item.privateDataDetected = markerPattern.test(data) || ['page-url', 'page-ref', 'referer'].some(k => privatePath(decoded(params.get(k) || '')));
    }
    evidence.requests.push(item); requestRecords.set(request, item);
  });
  context.on('response', async response => {
    const responseAt = Date.now();
    const request = response.request(); const u = new URL(response.url());
    const item = requestRecords.get(request);
    if (item) {
      item.responseStatus = response.status(); item.responseAt = Date.now();
      if (item.redirectChain && response.status() >= 200 && response.status() < 300) for (const related of evidence.requests) if (related.redirectChain === item.redirectChain) related.deliveryStatus = response.status();
    }
    if (u.origin === origin && u.pathname === '/api/analytics/consent' && request.method() === 'POST') {
      let requestBody, receipt;
      try { requestBody = request.postDataJSON(); receipt = await response.json(); } catch {}
      const valid = !!requestBody && !!receipt && receipt.event_id === requestBody.event_id && receipt.event_type === requestBody.event_type && receipt.text_version === requestBody.text_version && Number.isFinite(Date.parse(receipt.recorded_at));
      const at = responseAt;
      evidence.consentReceipts.push({ eventType: requestBody?.event_type || 'unknown', status: response.status(), matchingReceipt: valid, at });
      if (valid && requestBody.event_type === 'grant') lastGrantReceiptAt = at;
    }
  });
  context.on('requestfailed', request => {
    const u = new URL(request.url());
    if (u.origin === origin && ['document', 'script', 'stylesheet'].includes(request.resourceType())) { const code = request.failure()?.errorText?.match(/(?:net::)?ERR_[A-Z0-9_]+/); evidence.criticalFirstPartyNetworkFailures.push({ phase, resourceType: request.resourceType(), networkError: code?.[0] ?? 'network_failure' }); }
    const item = requestRecords.get(request); if (item) { item.failed = true; const code = request.failure()?.errorText?.match(/(?:net::)?ERR_[A-Z0-9_]+/); if (code) item.networkError = code[0]; }
  });
  page = await context.newPage();
  let documentErrors = 0;
  page.on('pageerror', () => { documentErrors++; evidence.documentErrors = documentErrors; });
  evidence.documentErrors = 0;

  if (!withdrawalOnly && !returnOnly) {
  phase = 'without_consent';
  await goto('/');
  await page.getByRole('dialog', { name: 'Статистика посещений', exact: true }).waitFor({ state: 'visible' });
  await page.waitForTimeout(3000);
  assert(analyticsRequests().length === 0 && (await state()).metrikaScripts === 0, 'analytics_before_consent');
  await observe('fresh_profile_no_consent');
  await choose('rejected'); await page.waitForTimeout(1000);
  await observe('initial_rejection');
  await safeReload(); await page.waitForTimeout(1500);
  assert((await state()).consent === 'rejected' && analyticsRequests().length === 0 && (await state()).metrikaScripts === 0, 'analytics_after_rejection');
  await observe('rejection_after_reload'); evidence.tests.withoutConsent = true;

  phase = 'after_consent';
  await openSettings(); await choose('accepted');
  try {
    await until(() => pageviews('/').some(r => (r.deliveryStatus ?? r.responseStatus) >= 200 && (r.deliveryStatus ?? r.responseStatus) < 300), 'initial_real_pageview_missing', 15000);
  } catch (error) {
    if (!evidence.requests.some(r => r.endpoint === 'tag.js' && r.networkError === 'net::ERR_NETWORK_CHANGED')) throw error;
    evidence.recoveredFromBrowserNetworkChange = true;
    await safeReload();
    await until(() => pageviews('/').some(r => (r.deliveryStatus ?? r.responseStatus) >= 200 && (r.deliveryStatus ?? r.responseStatus) < 300), 'initial_real_pageview_missing_after_network_recovery', 30000);
  }
  await page.waitForTimeout(2000);
  const firstScript = evidence.requests.find(r => r.endpoint === 'tag.js');
  assert(lastGrantReceiptAt && firstScript && firstScript.at >= lastGrantReceiptAt, 'script_before_registered_grant');
  assert(pageviews('/').length === 1, 'duplicate_initial_pageview');
  const init = await page.evaluate(() => window.__iii8ObservedMethods.find(c => c.method === 'init'));
  assert(init?.counterId === counter && init.options.defer === true && init.options.disableYtm === true, 'incorrect_counter_init');
  for (const key of ['webvisor', 'clickmap', 'trackLinks', 'accurateTrackBounce', 'trackHash', 'sendTitle', 'ecommerce']) assert(init.options[key] === false, 'optional_collection_enabled');
  evidence.initialization = init;
  await observe('initial_public_view_delivered', { realPageviews: pageviews('/').length });
  await publicNavigation('Публикации', '/publications');
  assert(pageviews('/publications').length === 1, 'duplicate_publications_pageview');
  await observe('client_navigation_publications', { realPageviews: pageviews('/publications').length });
  await publicNavigation('Документы', '/documents');
  assert(pageviews('/documents').length === 1, 'duplicate_documents_pageview');
  await observe('client_navigation_documents', { realPageviews: pageviews('/documents').length });
  evidence.tests.afterConsent = true;

  phase = 'private_routes';
  for (const path of ['/auth/login', '/customer/orders', '/admin/orders']) {
    if (!page.url().startsWith(origin + '/documents')) { await goto('/documents'); await until(async () => (await state()).metrikaScripts === 1, 'counter_not_active_before_private_transition'); await page.waitForTimeout(1800); }
    const before = Date.now();
    if (path === '/auth/login') {
      await page.getByRole('navigation', { name: 'Основная навигация', exact: true }).getByRole('link', { name: 'Вход заказчика', exact: true }).click();
    } else {
      // A real history/POP transition keeps the previously loaded document alive.
      await page.evaluate(path => {
        const current = history.state;
        history.pushState({ usr: null, key: crypto.randomUUID(), idx: (current?.idx ?? 0) + 1 }, '', path + '?token=iii8_synthetic_secret&order=iii8_synthetic_order&email=iii8-synthetic%40example.invalid#iii8_synthetic_fragment');
        dispatchEvent(new PopStateEvent('popstate', { state: history.state }));
      }, path);
    }
    await until(async () => (await state()).metrikaScripts === 0, 'counter_not_disposed_on_private_route');
    await page.waitForTimeout(800);
    const stopped = Date.now();
    await page.mouse.wheel(0, 400);
    const textbox = page.getByRole('textbox').first();
    if (await textbox.count()) await textbox.fill('iii8-synthetic@example.invalid');
    await page.waitForTimeout(4500);
    const methods = await page.evaluate(() => window.__iii8ObservedMethods);
    assert(methods.some(c => c.method === 'destruct' && c.at >= before), 'destruct_missing_on_private_transition');
    assert(analyticsRequests(stopped).length === 0, 'new_analytics_on_private_route');
    assert(!analyticsRequests().some(r => r.privateDataDetected), 'private_payload_detected');
    await observe('active_public_to_' + path.split('/')[1], { targetCategory: path.split('/')[1], newAnalyticsAfterStop: analyticsRequests(stopped).length, navigation: path === '/auth/login' ? 'UI Link' : 'history POP', unauthorizedOnly: true });
  }
  evidence.tests.privateRoutes = true;

  }

  if (!returnOnly) {
  phase = 'withdrawal';
  await goto('/documents');
  if (withdrawalOnly) {
    await page.getByRole('dialog', { name: 'Статистика посещений', exact: true }).waitFor({ state: 'visible' });
    await choose('accepted');
    await until(() => pageviews('/documents').some(r => (r.deliveryStatus ?? r.responseStatus) >= 200 && (r.deliveryStatus ?? r.responseStatus) < 300), 'standalone_withdrawal_counter_not_loaded', 30000);
    await observe('withdrawal_profile_real_counter_active');
  }
  await until(async () => (await state()).metrikaScripts === 1, 'counter_not_active_before_withdrawal');
  await page.waitForTimeout(1800);
  await openSettings(); const revokeStart = Date.now(); await choose('rejected');
  const receipt = evidence.consentReceipts.filter(c => c.eventType === 'withdraw' && c.matchingReceipt && c.at >= revokeStart).at(-1);
  assert(receipt?.status >= 200 && receipt?.status < 300, 'withdrawal_receipt_missing');
  const stopAt = Date.now();
  const methods = await page.evaluate(() => window.__iii8ObservedMethods);
  assert(methods.some(c => c.method === 'destruct' && c.at >= revokeStart), 'withdrawal_destruct_missing');
  await page.mouse.wheel(0, 500); await page.waitForTimeout(8000);
  assert(analyticsRequests(stopAt).length === 0 && (await state()).metrikaScripts === 0, 'new_analytics_after_withdrawal');
  await observe('withdrawal_committed_and_quiet', { observationMilliseconds: 8000, newAnalyticsAfterReceipt: analyticsRequests(stopAt).length, requestsStartedBeforeStop: analyticsRequests().filter(r => r.at < stopAt && r.responseAt >= stopAt).length });
  await safeReload(); await page.waitForTimeout(1800);
  assert((await state()).consent === 'rejected' && analyticsRequests(stopAt).length === 0, 'withdrawal_not_persistent');
  await observe('withdrawal_after_reload');
  const regrantAt = Date.now(); await openSettings(); await choose('accepted');
  await until(() => pageviews('/documents', regrantAt).some(r => (r.deliveryStatus ?? r.responseStatus) >= 200 && (r.deliveryStatus ?? r.responseStatus) < 300), 'reactivation_real_pageview_missing', 30000);
  await page.waitForTimeout(2000);
  assert(pageviews('/documents', regrantAt).length === 1, 'reactivation_duplicate_pageview');
  await observe('reactivation_after_new_consent', { realPageviews: pageviews('/documents', regrantAt).length });
  await openSettings(); await choose('rejected'); await page.waitForTimeout(1200);
  evidence.tests.withdrawal = true;
  }
  if (returnOnly) {
    phase = 'return_after_private';
    await goto('/');
    await page.getByRole('dialog', { name: 'Статистика посещений', exact: true }).waitFor({ state: 'visible' });
    await choose('accepted');
    await until(() => pageviews('/').some(r => (r.deliveryStatus ?? r.responseStatus) === 200), 'return_profile_initial_view_missing', 30000);
    await page.getByRole('navigation', { name: 'Основная навигация', exact: true }).getByRole('link', { name: 'Вход заказчика', exact: true }).click();
    await until(async () => (await state()).metrikaScripts === 0, 'return_profile_private_stop_missing');
    const returnAt = Date.now();
    await page.locator('header .brand').click();
    await page.waitForURL(origin + '/');
    await until(() => pageviews('/', returnAt).some(r => (r.deliveryStatus ?? r.responseStatus) === 200), 'ui_return_to_public_view_missing', 30000);
    await observe('ui_return_to_public_counter_active', { realPageviews: pageviews('/', returnAt).length });
    assert(pageviews('/', returnAt).length === 1, 'duplicate_ui_return_view');
    const reloadAt = Date.now();
    await safeReload();
    await until(() => pageviews('/', reloadAt).some(r => (r.deliveryStatus ?? r.responseStatus) === 200), 'public_reload_view_missing', 30000);
    await observe('public_reload_counter_active', { realPageviews: pageviews('/', reloadAt).length });
    await openSettings(); await choose('rejected');
    evidence.tests.returnAfterPrivate = true;
  }
  evidence.documentErrors = documentErrors;
  assert(documentErrors === 0, 'new_browser_runtime_error');
  assert(!analyticsRequests().some(r => r.privateDataDetected), 'private_payload_detected');
  evidence.all_required_passed = Object.values(evidence.tests).every(Boolean) && evidence.failures.length === 0;
} catch (error) {
  evidence.failures.push(String(error?.message || 'BrowserCheckFailed').replace(/https?:\/\/\S+/g, '[URL omitted]').slice(0, 180));
  evidence.failedPhase = phase;
  try { evidence.failedState = await state(); evidence.observedMethodsAtFailure = await page.evaluate(() => window.__iii8ObservedMethods); evidence.consentErrorVisible = await page.getByRole('alert').count() > 0; } catch {}
  evidence.all_required_passed = false;
} finally {
  evidence.thirdPartyHosts = [...new Set(evidence.requests.map(r => r.host))];
  evidence.consentRecordCounts = {
    grants: evidence.consentReceipts.filter(r => r.eventType === 'grant' && r.matchingReceipt).length,
    withdrawals: evidence.consentReceipts.filter(r => r.eventType === 'withdraw' && r.matchingReceipt).length,
  };
  if (browser) await browser.close();
  await writeFile(output, JSON.stringify(evidence, null, 2) + '\n');
  console.log(JSON.stringify({ all_required_passed: evidence.all_required_passed, tests: evidence.tests, failedPhase: evidence.failedPhase, failures: evidence.failures, externalRequests: evidence.requests.length }));
}
process.exitCode = evidence.all_required_passed ? 0 : 1;
