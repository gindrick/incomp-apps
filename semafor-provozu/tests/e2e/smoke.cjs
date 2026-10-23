/* End to end smoke test: server (dev přihlášení) + skutečný prohlížeč.
 *   SEMAFOR_E2E_URL=http://127.0.0.1:8765/semafor node tests/e2e/smoke.cjs
 * Ověřuje: přihlášení, načtení dat, žádné chyby CSP ani konzole, živé změny mezi dvěma uživateli,
 * pravidla (čtenář nezapíše, uživatel nezapíše do settings, soukromé To Do cizího nevidí),
 * zámek (lease) mezi uživateli, knihovny PDF, Moje práce podle e-mailu po migraci. */
const { chromium } = require('playwright');
const BASE = process.env.SEMAFOR_E2E_URL || 'http://127.0.0.1:8765/semafor';
let pass = 0, fail = 0;
function ok(cond, msg) { if (cond) { pass++; console.log('  ok  ' + msg); } else { fail++; console.log('  FAIL ' + msg); } }

async function open(browser, user) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(`${BASE}/auth/dev-login?u=${user}&next=${encodeURIComponent(new URL(BASE).pathname + '/')}`);
  await page.waitForFunction(() => document.querySelector('#conn') && /připojeno/.test(document.querySelector('#conn').textContent), null, { timeout: 15000 });
  return { ctx, page, errors };
}
const db = (page, fn, arg) => page.evaluate(async ([src, a]) => { const db = await window.claude.use('db'); return (new Function('db', 'a', 'return (' + src + ')(db, a)'))(db, a); }, [fn.toString(), arg]);

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
  const jan = await open(browser, 'jan');
  const bob = await open(browser, 'bob');
  const cyril = await open(browser, 'cyril');

  console.log('načtení');
  const counts = await jan.page.evaluate(async () => { const db = await window.claude.use('db'); const p = await db.collection('projects').get(); const t = await db.collection('tasks').get(); return [p.size, t.size]; });
  ok(counts[0] >= 44 && counts[1] >= 270, `projekty ${counts[0]}, úkoly ${counts[1]} načteny`);
  const me = await jan.page.evaluate(async () => (await window.claude.use('user')).me());
  ok(me.email === 'jan.kratky@hranipex.com' && me.isOwner === true, 'identita a role správce');
  ok(await jan.page.evaluate(() => !!(window.jspdf && window.html2canvas)), 'knihovny PDF načtené (CSP nonce)');
  ok(await jan.page.evaluate(() => /Jan Kratky/.test(document.getElementById('me-box').textContent)), 'hlavička ukazuje Jan Kratky');
  const myText = await jan.page.evaluate(() => document.getElementById('main').innerText);
  ok(!/Nejsi přihlášený/.test(myText), 'Moje práce bez varování o přihlášení');

  console.log('živé změny');
  const t0 = Date.now();
  await db(bob.page, (db) => db.collection('projects').doc('e2e_live').set({ title: 'E2E živá změna', department: 'hq', status: 'yellow', lifecycle: 'active', archived: false }));
  await jan.page.waitForFunction(async () => { const db = await window.claude.use('db'); const s = await db.collection('projects').get(); return s.docs.some(d => d.id === 'e2e_live'); }, null, { timeout: 8000 });
  ok(true, `Jan vidí projekt založený Bobem (${Date.now() - t0} ms)`);
  const seenP = jan.page.evaluate(() => new Promise(res => {
    window.claude.use('db').then(db => {
      const un = db.collection('projects').onSnapshot(s => { if (s.docs.some(d => d.id === 'e2e_live' && d.data().status === 'red')) { un(); res(true); } });
    });
    setTimeout(() => res(false), 8000);
  }));
  await db(bob.page, (db) => db.collection('projects').doc('e2e_live').update({ status: 'red', nested: { a: 1 } }));
  const seen = await seenP;
  ok(seen, 'update se propsal do onSnapshot');

  console.log('pravidla');
  const readerErr = await db(cyril.page, (db) => db.collection('tasks').doc('x').set({ title: 'nesmí' }).then(() => 'zapsáno', e => e.code));
  ok(readerErr === 'permission_denied', 'čtenář nezapíše (' + readerErr + ')');
  const setErr = await db(bob.page, (db) => db.collection('settings').doc('finance').set({ rateEurCzk: 99 }).then(() => 'zapsáno', e => e.code));
  ok(setErr === 'permission_denied', 'uživatel nezapíše settings (' + setErr + ')');
  const okAdmin = await db(jan.page, (db) => db.collection('settings').doc('finance').set({ rateEurCzk: 24.5, base: 'CZK', updatedAt: Date.now(), log: [] }).then(() => 'ok', e => e.code));
  ok(okAdmin === 'ok', 'správce zapíše settings');
  await db(bob.page, (db) => db.doc('data/users/dev-bob/private').collection('todos').doc('b1').set({ title: 'Bobovo soukromé', done: false }));
  const spy = await db(jan.page, (db) => db.doc('data/users/dev-bob/private').collection('todos').get().then(s => 'viděno ' + s.size, e => e.code));
  ok(spy === 'permission_denied', 'cizí soukromé To Do nevidí ani správce (' + spy + ')');
  const own = await db(bob.page, (db) => db.doc('data/users/dev-bob/private').collection('todos').get().then(s => s.size));
  ok(own === 1, 'vlastní soukromé To Do vidí');

  console.log('zámek');
  const l1 = await db(jan.page, (db) => db.collection('projects').doc('e2e_live').acquire({ holder: 'jan:1', ttlMs: 20000 }));
  const l2 = await db(bob.page, (db) => db.collection('projects').doc('e2e_live').acquire({ holder: 'bob:1', ttlMs: 20000 }));
  ok(l1.acquired === true && l2.acquired === false && !!l2.expiresAt, 'druhý zámek nedostane');
  await db(jan.page, (db) => db.collection('projects').doc('e2e_live').acquire({ holder: 'jan:1', ttlMs: 1 }));
  await new Promise(r => setTimeout(r, 20));
  const l3 = await db(bob.page, (db) => db.collection('projects').doc('e2e_live').acquire({ holder: 'bob:1', ttlMs: 20000 }));
  ok(l3.acquired === true, 'po uvolnění zámek dostane');

  console.log('záložní dotazování (proxy bez SSE)');
  {
    const ctx = await browser.newContext();
    await ctx.addInitScript(() => { window.EventSource = undefined; });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/auth/dev-login?u=cyril&next=${encodeURIComponent(new URL(BASE).pathname + '/')}`);
    await page.waitForFunction(() => /připojeno/.test(document.querySelector('#conn').textContent), null, { timeout: 15000 });
    const t1 = Date.now();
    await db(bob.page, (db) => db.collection('tasks').doc('e2e_poll').set({ title: 'E2E dotazování', department: 'hq', status: 'todo', archived: false }));
    const got = await page.waitForFunction(async () => { const db = await window.claude.use('db'); const s = await db.collection('tasks').get(); return s.docs.some(d => d.id === 'e2e_poll'); }, null, { timeout: 12000 }).then(() => true, () => false);
    ok(got, `bez SSE se změna dostane dotazováním (${Date.now() - t1} ms)`);
    await db(bob.page, (db) => db.collection('tasks').doc('e2e_poll').delete());
    await ctx.close();
  }

  console.log('mazání a UI');
  await db(bob.page, (db) => db.collection('projects').doc('e2e_live').delete());
  await jan.page.waitForFunction(async () => { const db = await window.claude.use('db'); const s = await db.collection('projects').get(); return !s.docs.some(d => d.id === 'e2e_live'); }, null, { timeout: 8000 });
  ok(true, 'smazání se propsalo');
  await jan.page.click('[data-nav="projects"]');
  await jan.page.waitForTimeout(500);
  const projText = await jan.page.evaluate(() => document.getElementById('main').innerText);
  ok(/Modernizace posilovny/.test(projText), 'seznam projektů ukazuje migrovaná data');

  for (const [n, u] of [['jan', jan], ['bob', bob], ['cyril', cyril]]) {
    const errs = u.errors.filter(e => !/permission_denied|403|Forbidden/i.test(e));
    ok(errs.length === 0, `${n}: žádné chyby v konzoli ${errs.length ? JSON.stringify(errs.slice(0, 3)) : ''}`);
  }
  await browser.close();
  console.log(`\n${pass} ok, ${fail} chyb`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
