// The map view (docs/STORY_DESIGN.md §3.6, Phase V) in a real browser.
//
//   node tests/js/mapview.e2e.mjs <base-url> [<screenshot-dir>] [<extra page url> ...]
//
// <base-url> serves a preview site (scripts/build_preview.py): its replay.html
// is opened at a phone held upright (390 x 844) and an iPad (820 x 1180), and
// checked: follow mode frames 1885, 1914 and 1966; a drag, a pinch and a
// double tap each move the map and free the camera; free mode holds still
// across Next year and Recentre brings it back; a mark's card opens on a tap
// and closes on a tap on the map; and no page logs an error. Extra page URLs
// (the archived games' Replay pages) are opened and must log no error.
// tests/test_mapview.py runs it where Playwright is installed.
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

const [base, shots = null, ...extra] = process.argv.slice(2);
const failures = [];
const checks = [];
const errors = [];
const check = (name, ok, detail = '') => {
  checks.push(name);
  if (!ok) failures.push(`${name}${detail ? `: ${detail}` : ''}`);
};

const wait = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

async function settled(page) {
  await page.waitForFunction(() => window.hocReplay && !window.hocReplay.busy(), null, { timeout: 15000 });
  await wait(250);
}

// A fresh load each time: going to the URL already open changes no hash.
async function open(page, turn) {
  await page.goto('about:blank');
  await page.goto(`${base}/replay.html#turn-${turn}`);
  await page.waitForFunction((t) => window.hocReplay && window.hocReplay.turn() === t, turn, { timeout: 20000 });
  await settled(page);
  if (await page.isVisible('#mv-full-continue')) await page.click('#mv-full-continue');
}

// The ground the camera framed, in screen pixels, against the part of the
// stage between the bars.
async function framing(page) {
  return page.evaluate(() => {
    const feds = window.hocReplay.frame();
    let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
    for (const fed of feds) {
      const r = document.querySelector(`#map-fills path[data-fed="${fed}"]`).getBoundingClientRect();
      x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top); x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom);
    }
    const top = document.querySelector('.mv-top').getBoundingClientRect().bottom;
    const bottom = document.querySelector('.mv-bottom').getBoundingClientRect().top;
    return { feds: feds.length, ground: [x0, y0, x1, y1], area: [0, top, window.innerWidth, bottom] };
  });
}

function inside(f, slack = 2) {
  const [x0, y0, x1, y1] = f.ground;
  const [a0, b0, a1, b1] = f.area;
  return f.feds > 0 && x0 >= a0 - slack && y0 >= b0 - slack && x1 <= a1 + slack && y1 <= b1 + slack;
}

const moved = (a, b) => ['x', 'y', 'w'].some((k) => Math.abs(a[k] - b[k]) > 1e-6 * Math.max(1, Math.abs(a[k])));

async function touch(cdp, type, points) {
  await cdp.send('Input.dispatchTouchEvent', {
    type, touchPoints: points.map(([x, y], id) => ({ x, y, id, radiusX: 2, radiusY: 2, force: 1 })),
  });
}

async function viewport(browser, size, label) {
  const context = await browser.newContext({
    viewport: size, hasTouch: true, isMobile: size.width < 700, deviceScaleFactor: 2,
  });
  const page = await context.newPage();
  page.on('console', (m) => { if (m.type() === 'error') errors.push(`${label}: ${m.text()}`); });
  page.on('pageerror', (e) => errors.push(`${label}: ${e.message}`));
  const cdp = await context.newCDPSession(page);

  // Follow mode frames the headline's ground: 1885, 1914, 1966.
  for (const [turn, year] of [[19, 1885], [48, 1914], [100, 1966]]) {
    await open(page, turn);
    const f = await framing(page);
    check(`${label}: follow mode frames ${year}`, inside(f), JSON.stringify(f));
    check(`${label}: follow mode in ${year}`, (await page.evaluate(() => window.hocReplay.mode())) === 'follow');
  }

  // A one-finger drag pans, and frees the camera. The gestures start on open
  // map, below the top bar: the card swallows its own touches.
  await open(page, 30);
  const topBar = await page.evaluate(() => document.querySelector('.mv-top').getBoundingClientRect().bottom);
  const centre = [size.width / 2, topBar + 90];
  let before = await page.evaluate(() => window.hocReplay.view());
  await touch(cdp, 'touchStart', [centre]);
  for (let i = 1; i <= 6; i += 1) await touch(cdp, 'touchMove', [[centre[0] - 12 * i, centre[1] + 8 * i]]);
  await touch(cdp, 'touchEnd', []);
  await wait(150);
  let after = await page.evaluate(() => window.hocReplay.view());
  check(`${label}: a drag moves the map`, moved(before, after) && Math.abs(after.w - before.w) < 1e-6);
  check(`${label}: a gesture frees the camera`, (await page.evaluate(() => window.hocReplay.mode())) === 'free');
  check(`${label}: Recentre is offered in free mode`, await page.isVisible('#mv-recentre'));

  // Free mode holds still across Next year.
  before = await page.evaluate(() => window.hocReplay.view());
  await page.click('#story-next');
  await page.waitForFunction(() => window.hocReplay.turn() === 31);
  await settled(page);
  after = await page.evaluate(() => window.hocReplay.view());
  check(`${label}: free mode holds still across Next year`, !moved(before, after));
  if (await page.isVisible('#mv-recentre')) await page.click('#mv-recentre');
  await settled(page);
  await wait(1000);
  check(`${label}: Recentre returns to follow mode`, (await page.evaluate(() => window.hocReplay.mode())) === 'follow'
    && !(await page.isVisible('#mv-recentre')));
  const f = await framing(page);
  check(`${label}: Recentre frames the year`, f.feds === 0 || inside(f), JSON.stringify(f));

  // A pinch zooms.
  before = await page.evaluate(() => window.hocReplay.view());
  await touch(cdp, 'touchStart', [[centre[0] - 30, centre[1]], [centre[0] + 30, centre[1]]]);
  for (let i = 1; i <= 6; i += 1) {
    await touch(cdp, 'touchMove', [[centre[0] - 30 - 15 * i, centre[1]], [centre[0] + 30 + 15 * i, centre[1]]]);
  }
  await touch(cdp, 'touchEnd', []);
  await wait(150);
  after = await page.evaluate(() => window.hocReplay.view());
  check(`${label}: a pinch zooms in`, after.w < before.w * 0.6, `${before.w} -> ${after.w}`);

  // A double tap zooms in about the tap.
  before = after;
  await page.touchscreen.tap(centre[0], centre[1]);
  await wait(60);
  await page.touchscreen.tap(centre[0], centre[1]);
  await wait(1200);
  after = await page.evaluate(() => window.hocReplay.view());
  check(`${label}: a double tap zooms in`, after.w < before.w * 0.75 || before.w <= 3.01, `${before.w} -> ${after.w}`);

  // A mark's card: open on a tap, closed by a tap on the map.
  await open(page, 30);
  if (await page.isVisible('#mv-recentre')) await page.click('#mv-recentre');
  await settled(page);
  await page.click('.mv-card-close');
  check(`${label}: the headline card closes`, !(await page.isVisible('#mv-card')));
  // A mark whose badge is on open map, between the bars.
  const target = await page.evaluate(() => {
    const top = document.querySelector('.mv-top').getBoundingClientRect().bottom;
    const bottom = document.querySelector('.mv-bottom').getBoundingClientRect().top;
    const seen = [...document.querySelectorAll('[data-mark] .mk-bg')].map((c) => {
      const r = c.getBoundingClientRect();
      return { id: c.closest('[data-mark]').getAttribute('data-mark'), x: r.left, y: r.top, width: r.width, height: r.height };
    }).filter((b) => b.y > top + 4 && b.y + b.height < bottom - 4 && b.x > 4 && b.x + b.width < window.innerWidth - 4);
    const heads = window.hocReplay.marks().filter((m) => m.headline).map((m) => m.id);
    return seen.find((b) => !heads.includes(b.id)) || seen[0] || null;
  });
  check(`${label}: a mark is on screen`, Boolean(target));
  const box = target;
  await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
  await wait(200);
  const card = await page.evaluate(() => window.hocReplay.card());
  check(`${label}: a tap on a mark opens its card`, await page.isVisible('#mv-card') && card && card.id === target.id,
    JSON.stringify(card));
  const cardBox = await (await page.$('#mv-card')).boundingBox();
  const covers = cardBox.x < box.x + box.width && box.x < cardBox.x + cardBox.width
    && cardBox.y < box.y + box.height && box.y < cardBox.y + cardBox.height;
  check(`${label}: the card does not cover its mark`, !covers);
  await page.touchscreen.tap(8, size.height / 2);
  await wait(200);
  check(`${label}: a tap on the map closes the card`, !(await page.isVisible('#mv-card')));
  await page.touchscreen.tap(8, size.height / 2);
  await wait(400);

  if (shots) {
    for (const [turn, year] of [[1, 1867], [19, 1885], [48, 1914], [70, 1936], [100, 1966]]) {
      await open(page, turn);
      await wait(900);
      await page.screenshot({ path: `${shots}/${year}-${size.width}.png` });
    }
  }
  await context.close();
}

const browser = await playwright.chromium.launch();
try {
  await viewport(browser, { width: 390, height: 844 }, '390x844');
  await viewport(browser, { width: 820, height: 1180 }, '820x1180');
  for (const url of extra) {
    const page = await browser.newPage();
    page.on('console', (m) => { if (m.type() === 'error') errors.push(`${url}: ${m.text()}`); });
    page.on('pageerror', (e) => errors.push(`${url}: ${e.message}`));
    await page.goto(url);
    await wait(2500);
    const next = await page.$('#story-next');
    if (next && await next.isVisible() && await next.isEnabled()) {
      await next.click();
      await wait(1500);
    }
    check(`${url} renders`, Boolean(await page.$('#map-fills path')));
    await page.close();
  }
} catch (error) {
  failures.push(`the checks stopped: ${error.message.split('\n')[0]}`);
} finally {
  await browser.close();
}
check('no page logged an error', errors.length === 0, errors.join(' | '));
console.log(JSON.stringify({ ok: failures.length === 0, failures, checks: checks.length, errors }));
process.exit(failures.length ? 1 : 0);
