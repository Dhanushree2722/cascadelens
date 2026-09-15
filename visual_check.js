// Visual walkthrough of the CascadeLens dashboard; writes screenshots to ./.shots.
const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join(process.env.CASCADE_TOOLS, 'node_modules', 'playwright'));

const BASE = process.env.CASCADE_URL || 'http://127.0.0.1:8000/';
const OUT = path.join(__dirname, '.shots');
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const problems = [];
  page.on('pageerror', e => problems.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') problems.push('console: ' + m.text()); });
  const dialogs = [];
  page.on('dialog', async d => { dialogs.push(d.message()); await d.dismiss(); });
  const shot = async (name) => { await page.waitForTimeout(150); await page.screenshot({ path: path.join(OUT, name + '.png'), fullPage: true }); };
  const runDone = () => page.waitForResponse(r => r.url().endsWith('/api/simulate'));
  const report = {};

  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.querySelectorAll('#ledger tbody tr').length > 0);
  await shot('01-initial-S1-medium');
  report.initial = await page.$$eval('#metrics .metric', els => els.map(e => e.innerText.replace(/\n/g, ' | ')));

  // Hazard dropdown: every option runs and changes the ledger cause text.
  report.hazards = {};
  for (const h of await page.$$eval('#hazard option', os => os.map(o => o.value))) {
    await page.selectOption('#hazard', h);
    await Promise.all([runDone(), page.click('#run')]);
    await page.waitForFunction(v => document.querySelector('#ledger tbody tr td:nth-child(5)').innerText.startsWith(v), h);
    report.hazards[h] = await page.$eval('#ledger tbody tr td:nth-child(5)', e => e.innerText);
  }
  await page.selectOption('#hazard', 'flood');

  // Severity dropdown: repair hour changes 24/36/48.
  report.severity = {};
  for (const s of ['low', 'medium', 'high']) {
    await page.selectOption('#severity', s);
    await Promise.all([runDone(), page.click('#run')]);
    await page.waitForFunction(s => document.querySelector('#ledger tbody tr td:nth-child(5)').innerText.includes(s), s);
    report.severity[s] = await page.$eval('#ledger tbody tr td:nth-child(6)', e => e.innerText);
  }
  await shot('02-high-severity');

  // Slider: colours change over time.
  await page.selectOption('#severity', 'medium');
  await Promise.all([runDone(), page.click('#run')]);
  await page.waitForFunction(() => document.querySelector('#hourLabel').innerText.includes('hour 0'));
  const count = async () => page.evaluate(() => ({
    failed: document.querySelectorAll('#map circle[fill="#ef4444"]').length,
    backup: document.querySelectorAll('#map circle[fill="#f59e0b"]').length,
    ok: document.querySelectorAll('#map circle[fill="#22c55e"]').length,
    label: document.getElementById('hourLabel').innerText }));
  report.slider = {};
  for (const t of [0, 3, 6, 20, 38, 48]) {
    await page.fill('#hour', String(t)); await page.dispatchEvent('#hour', 'input');
    report.slider[t] = await count();
    if (t === 6) await shot('03-slider-hour6');
    if (t === 48) await shot('04-slider-hour48-recovered');
  }
  report.tooltip = await page.$eval('#map g title', e => e.textContent);

  // Horizon input: slider max follows it; recovery not reached within short horizon.
  await page.fill('#horizon', '12');
  await Promise.all([runDone(), page.click('#run')]);
  await page.waitForFunction(() => document.getElementById('hour').max === '12');
  report.horizon12 = await page.$$eval('#metrics .metric', els => els.map(e => e.innerText.replace(/\n/g, ' | ')));
  await shot('05-horizon12-not-recovered');
  await page.fill('#horizon', '48');

  // Checkboxes: multi-failure scenario, then compare.
  await page.check('#assetList input[value="S3"]');
  await page.check('#assetList input[value="W1"]');
  report.checked = await page.$$eval('#assetList input:checked', els => els.map(e => e.value));
  await Promise.all([
    page.waitForResponse(r => r.url().endsWith('/api/compare') && r.status() === 200),
    page.click('#compare')]);
  await page.waitForFunction(() => !document.getElementById('comparePanel').hidden && document.querySelectorAll('#options tbody tr').length > 0);
  report.compare = await page.$$eval('#options tbody tr', els => els.map(e => e.innerText.replace(/\t/g, ' | ')));
  report.bestRowHighlighted = await page.$$eval('#options tbody tr.best', els => els.length);
  report.explanation = await page.textContent('#explanation');
  await shot('06-compare-S1-S3-W1');

  // Run again hides stale comparison.
  await Promise.all([runDone(), page.click('#run')]);
  await page.waitForFunction(() => document.getElementById('comparePanel').hidden);
  report.compareHiddenAfterRun = true;

  // Error handling: none selected, bad horizon.
  await page.$$eval('#assetList input:checked', els => els.forEach(e => e.click()));
  await page.click('#run'); await page.waitForTimeout(300);
  await page.check('#assetList input[value="S2"]');
  await page.fill('#horizon', '500');
  await Promise.all([runDone(), page.click('#run')]); await page.waitForTimeout(300);
  report.dialogs = dialogs;
  await page.fill('#horizon', '48');
  await Promise.all([runDone(), page.click('#run')]);
  await page.waitForFunction(() => document.querySelectorAll('#ledger tbody tr').length > 0);
  await shot('07-S2-after-errors');

  // Hover title on a node (native tooltip via <title> on the group).
  await page.hover('#map g:nth-of-type(1)');

  // Narrow (phone) layout.
  await page.setViewportSize({ width: 420, height: 900 });
  await page.waitForTimeout(200);
  report.mobileCols = await page.evaluate(() => getComputedStyle(document.querySelector('main')).gridTemplateColumns);
  await shot('08-mobile-420');

  report.problems = problems;
  console.log(JSON.stringify(report, null, 1));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
