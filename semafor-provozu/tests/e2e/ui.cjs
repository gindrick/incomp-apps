/* End to end test skutečného UI nad serverem (dev přihlášení, migrovaná data).
 *   SEMAFOR_E2E_URL=http://127.0.0.1:8765/semafor node tests/e2e/ui.cjs
 * Rychlé zadání úkolu a historie, živé zobrazení u druhého uživatele, zámek detailu,
 * příloha (upload + stažení přes /_blob), charter jako PDF (jsPDF pod CSP). */
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = process.env.SEMAFOR_E2E_URL || 'http://127.0.0.1:8765/semafor';
const PATH = new URL(BASE).pathname;
let pass = 0, fail = 0;
function ok(c, m) { if (c) { pass++; console.log('  ok  ' + m); } else { fail++; console.log('  FAIL ' + m); } }
async function open(browser, user) {
  const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage(); const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(`${BASE}/auth/dev-login?u=${user}&next=${encodeURIComponent(PATH + '/')}`);
  await page.waitForFunction(() => /připojeno/.test(document.querySelector('#conn').textContent), null, { timeout: 15000 });
  return { page, errors };
}
const title = 'E2E úkol z UI ' + Date.now().toString(36);
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
  const jan = await open(browser, 'jan'), bob = await open(browser, 'bob');

  console.log('rychlé zadání');
  await jan.page.fill('#qa-my', title);
  await jan.page.press('#qa-my', 'Enter');
  await jan.page.waitForFunction(t => document.getElementById('main').innerText.includes(t), title, { timeout: 8000 });
  ok(true, 'úkol se objevil v Moje práce');
  await jan.page.waitForTimeout(1500);   // historie se zapisuje po uložení položky
  const rec = await jan.page.evaluate(async t => {
    const db = await window.claude.use('db'); const s = await db.collection('tasks').get();
    const d = s.docs.find(x => x.data().title === t); if (!d) return null;
    const h = await db.collection('history').doc(d.id).get();
    return { id: d.id, data: d.data(), hist: h.exists ? Object.values(h.data().events || {}).map(e => e.type) : [] };
  }, title);
  ok(rec && rec.data.ownerEmail === 'jan.kratky@hranipex.com', 'vlastník = přihlášený (e-mail)');
  ok(rec && rec.data.createdById === 'dev-jan', 'createdById = id účtu');
  ok(rec && rec.hist.includes('created'), 'historie: událost created');

  console.log('druhý uživatel a zámek');
  await bob.page.click('[data-nav="hq"]'); await bob.page.click('[data-tab="tasks"]');
  await bob.page.waitForFunction(t => document.getElementById('main').innerText.includes(t), title, { timeout: 8000 });
  ok(true, 'Bob vidí úkol v kanbanu Ostatní / HQ bez obnovení stránky');
  await jan.page.click(`#main [data-open]:has-text("${title}")`);
  await jan.page.waitForSelector('#modal-root .modal', { timeout: 5000 });
  await jan.page.waitForTimeout(500);
  await bob.page.click(`#main [data-open]:has-text("${title}")`);
  await bob.page.waitForSelector('#modal-root .modal', { timeout: 5000 });
  await bob.page.waitForFunction(() => /Upravuje|upravuje/.test((document.getElementById('f-lock') || {}).innerText || ''), null, { timeout: 5000 }).then(() => ok(true, 'Bob vidí lištu zámku "Upravuje"'), () => ok(false, 'lišta zámku u Boba'));
  await bob.page.keyboard.press('Escape');

  console.log('příloha');
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64');
  fs.writeFileSync('/tmp/e2e-pixel.png', png);
  if (!(await jan.page.$('#att-file'))) { const more = await jan.page.$('#modal-root [data-action="toggle-more"]'); if (more) await more.click(); }
  const fileInput = await jan.page.$('#att-file');
  if (fileInput) {
    await fileInput.setInputFiles('/tmp/e2e-pixel.png');
    await jan.page.waitForFunction(() => /Nahráno/.test((document.getElementById('att-msg') || {}).textContent || ''), null, { timeout: 8000 }).then(() => ok(true, 'upload přílohy'), () => ok(false, 'upload přílohy: ' + 'bez hlášení Nahráno'));
    const href = await jan.page.$eval('#att-box .att-row a', a => a.getAttribute('href')).catch(() => '');
    ok(href.startsWith(PATH + '/_blob/'), 'odkaz přílohy s base path: ' + href);
    const st = await jan.page.evaluate(async h => (await fetch(h)).status, href);
    ok(st === 200, 'příloha jde stáhnout (' + st + ')');
  } else ok(false, 'v detailu není pole pro nahrání souboru');
  await jan.page.keyboard.press('Escape');
  await jan.page.waitForTimeout(300);

  console.log('charter PDF');
  await jan.page.click('[data-nav="projects"]');
  await jan.page.click('#main [data-open]:has-text("Modernizace posilovny")');
  await jan.page.waitForSelector('#modal-root [data-action="charter-open"]', { timeout: 5000 });
  await jan.page.click('#modal-root [data-action="charter-open"]');
  await jan.page.waitForSelector('[data-action="charter-pdf"]:not([disabled])', { timeout: 10000 });
  const [dl] = await Promise.all([jan.page.waitForEvent('download', { timeout: 30000 }), jan.page.click('[data-action="charter-pdf"]')]);
  const pdfPath = '/tmp/e2e-charter.pdf'; await dl.saveAs(pdfPath);
  const head = fs.readFileSync(pdfPath).subarray(0, 5).toString();
  ok(/\.pdf$/.test(dl.suggestedFilename()) && head === '%PDF-', 'charter stažen jako PDF: ' + dl.suggestedFilename() + ' ' + fs.statSync(pdfPath).size + ' B');

  for (const [n, u] of [['jan', jan], ['bob', bob]]) ok(u.errors.length === 0, `${n}: bez chyb v konzoli ${JSON.stringify(u.errors.slice(0, 3))}`);
  await jan.page.screenshot({ path: '/tmp/e2e-charter.png' });
  await browser.close();
  console.log(`\n${pass} ok, ${fail} chyb`); process.exit(fail ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
