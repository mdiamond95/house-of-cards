// The hex board's preview (docs/hex-trial/v2/README.md) in a real browser.
//
//   node tests/js/hexboard.e2e.mjs <base-url> [<screenshot-dir>]
//
// <base-url> serves the hex preview (outputs/site/preview-hex/, built by
// scripts/build_preview.py on meridian-hex-v1.0.5). At a phone held upright
// (390 x 844) it checks:
//
//   * the camera can come close enough to tell Toronto's city hexes apart;
//   * a unit is drawn closed until its opening year and open from it:
//     Winnipeg's extra hexes in 1872 and 1874, Calgary's in 1893 and 1895;
//   * the provincial and territorial borders are those of the year shown, and
//     change on the years the atlas changes (1867, 1871, 1905, 1949), with the
//     jurisdictions named at wide zoom and not when close;
//   * no page logs an error.
//
// With a screenshot directory it saves those views and one year (1912) turn
// by turn. tests/test_mapview.py runs it where Playwright is installed.
//
// Prints one JSON line: { ok, failures, checks, errors }.

import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';

function loadPlaywright() {
  const bases = [import.meta.url];
  try {
    bases.push(`${execSync('npm root -g', { encoding: 'utf8' }).trim()}/`);
  } catch (error) { /* no npm */ }
  for (const base of bases) {
    try {
      return createRequire(base)('playwright');
    } catch (error) { /* try the next */ }
  }
  return null;
}

const playwright = loadPlaywright();
if (!playwright) {
  console.log(JSON.stringify({ ok: null, skipped: 'playwright is not installed' }));
  process.exit(0);
}

const [base, shots = null] = process.argv.slice(2);
const failures = [];
const checks = [];
const errors = [];
const check = (name, ok, detail = '') => {
  checks.push(name);
  if (!ok) failures.push(`${name}${detail ? `: ${detail}` : ''}`);
};
const wait = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });
const YEAR0 = 1866;
const R = (page, fn, arg) => page.evaluate(fn, arg);

async function settled(page) {
  await page.waitForFunction(() => window.hocReplay && !window.hocReplay.busy(), null, { timeout: 20000 });
  await wait(250);
}

async function open(page, year) {
  const turn = year - YEAR0;
  await page.goto('about:blank');
  await page.goto(`${base}/replay.html#turn-${turn}`);
  await page.waitForFunction((t) => window.hocReplay && window.hocReplay.turn() === t, turn, { timeout: 20000 });
  await settled(page);
  if (await page.isVisible('#mv-full-continue')) await page.click('#mv-full-continue');
  await settled(page);
}

async function shot(page, name) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.jpg`, type: 'jpeg', quality: 80 });
}

async function look(page, name, w) {
  check(`the camera finds ${name}`, await R(page, ([n, width]) => window.hocReplay.look(n, width), [name, w]));
  await wait(400);
}

const browser = await playwright.chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(e.message));

  // Toronto in 1867: close enough to tell its city hexes apart.
  await open(page, 1867);
  const minW = await R(page, () => window.hocReplay.minW());
  check('the camera comes within a few city hexes', minW <= 30, String(minW));
  await look(page, 'Toronto', 34);
  const view = await R(page, () => window.hocReplay.view());
  check('the camera holds Toronto close', view.w <= 35, String(view.w));
  check('no jurisdiction is named when close', (await R(page, () => window.hocReplay.borders())).drawn === 0);
  await shot(page, 'toronto-1867');

  // A unit closed until its year, open from it.
  for (const [year, unit, closed, frame] of [
    [1872, 'Winnipeg Kildonan', true, 'Winnipeg'], [1874, 'Winnipeg Kildonan', false, 'Winnipeg'],
    [1893, 'Calgary Signal Hill', true, 'Calgary'], [1895, 'Calgary Signal Hill', false, 'Calgary'],
  ]) {
    await open(page, year);
    check(`${unit} is ${closed ? 'closed' : 'open'} in ${year}`,
      (await R(page, (n) => window.hocReplay.closed(n), unit)) === closed);
    check(`${frame}'s core is open in ${year}`, (await R(page, (n) => window.hocReplay.closed(n), frame)) === false);
    await look(page, frame, 40);
    await shot(page, `${frame.toLowerCase()}-${year}`);
  }

  // The borders of the year, named at wide zoom.
  const expected = {
    1867: ['Ontario', 'Quebec', 'Nova Scotia', 'New Brunswick', "Rupert's Land", 'British Columbia', 'Newfoundland'],
    1871: ['Manitoba', 'North-West Territories', 'British Columbia'],
    1905: ['Alberta', 'Saskatchewan', 'Yukon Territory'],
    1949: ['Newfoundland', 'Alberta'],
  };
  const spans = [];
  for (const year of [1867, 1871, 1905, 1949]) {
    await open(page, year);
    await R(page, () => window.hocReplay.whole());
    await wait(500);
    const b = await R(page, () => window.hocReplay.borders());
    check(`borders are drawn for ${year}`, b && b.d > 1000 && b.from <= year && (b.to === null || year <= b.to),
      JSON.stringify(b && { from: b.from, to: b.to, d: b.d }));
    check(`${year}'s jurisdictions are its own`, b && expected[year].every((n) => b.names.includes(n)), b && b.names.join(', '));
    check(`jurisdictions are named at wide zoom in ${year}`, b && b.drawn >= 5, b && String(b.drawn));
    spans.push(b && b.from);
    await shot(page, `country-${year}`);
  }
  check('the borders change on the years the atlas changes', new Set(spans).size === 4, spans.join(','));

  // One year turn by turn (1912: Timmins's year, and Manitoba, Ontario and
  // Quebec take the North).
  if (shots) {
    await open(page, 1912);
    const n = (await R(page, () => window.hocReplay.order())).length;
    for (let i = 0; i < n; i += 1) {
      await wait(1100);
      const p = await R(page, () => window.hocReplay.part());
      await shot(page, `1912-${String(i).padStart(2, '0')}-${p.kind === 'house' ? 'house' : p.kind}`);
      if (i < n - 1) {
        await page.click('#story-next');
        await settled(page);
      }
    }
  }
  await context.close();
} catch (error) {
  failures.push(`the checks stopped: ${error.message.split('\n')[0]}`);
} finally {
  await browser.close();
}
check('no page logged an error', errors.length === 0, errors.join(' | '));
console.log(JSON.stringify({ ok: failures.length === 0, failures, checks: checks.length, errors }));
process.exit(failures.length ? 1 : 0);
