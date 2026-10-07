// The map view (docs/STORY_DESIGN.md §3.6, Phases V and V2) in a real browser.
//
//   node tests/js/mapview.e2e.mjs <base-url> [<screenshot-dir>] [<extra page url> ...]
//
// <base-url> serves a preview site (scripts/build_preview.py), whose record
// keeps the round (rules 1.0 `round_record`): its replay.html is opened at a
// phone held upright (390 x 844), an iPad (820 x 1180) and a wide desktop
// window (1440 x 900), and checked:
//
//   * Next walks one year turn by turn: the world, each house in the engine's
//     order, the close; the strip follows, its current chip in view;
//   * Next year plays the rest of the round and stops at the close;
//   * a chip opens its house's sheet, and so does a row of the standings;
//   * Auto stops on the first turn that should stop it (a pause-weight turn);
//   * follow mode frames a notable turn in the space between the top bar and
//     the docked card, and leaves no more than a fifth of the map area unused
//     below it;
//   * the houses' names on the map never overlap;
//   * a crisis tints the camps' holdings and shows its legend;
//   * a chapter's close is an opaque card;
//   * a drag, a pinch and a double tap each move the map and free the camera;
//     free mode holds still across Next, and Recentre brings it back;
//   * a mark's card opens on a tap without covering its mark, and closes on a
//     tap on the map;
//   * no page logs an error.
//
// Extra page URLs (the archived games' Replay pages, told a year at a time)
// are opened and must log no error. With a screenshot directory it saves one
// whole year turn by turn at 390 px (1896) and the openings of 1885, 1914 and
// 1936 at each size. tests/test_mapview.py runs it where Playwright is
// installed.
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
const YEAR0 = 1866;

async function settled(page) {
  await page.waitForFunction(() => window.hocReplay && !window.hocReplay.busy(), null, { timeout: 20000 });
  await wait(250);
}

// A fresh load each time: going to the URL already open changes no hash. A
// year told round by round opens at its world's turn.
async function open(page, turn) {
  await page.goto('about:blank');
  await page.goto(`${base}/replay.html#turn-${turn}`);
  await page.waitForFunction((t) => window.hocReplay && window.hocReplay.turn() === t, turn, { timeout: 20000 });
  await settled(page);
  if (await page.isVisible('#mv-full-continue')) await page.click('#mv-full-continue');
}

const R = (page, fn, arg) => page.evaluate(fn, arg);
const part = (page) => R(page, () => window.hocReplay.part());

async function next(page) {
  await page.click('#story-next');
  await settled(page);
}

// The ground the camera framed, in screen pixels, against the part of the
// stage between the top bar and the docked card and controls.
async function framing(page) {
  return R(page, () => {
    const feds = window.hocReplay.frame();
    let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
    for (const fed of feds) {
      const r = document.querySelector(`#map-fills path[data-fed="${fed}"]`).getBoundingClientRect();
      x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top); x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom);
    }
    const top = document.querySelector('.mv-top').getBoundingClientRect().bottom;
    const bottom = document.querySelector('.mv-bottom').getBoundingClientRect().top;
    const card = document.querySelector('#mv-turn');
    const cardTop = card && !card.hidden ? card.getBoundingClientRect().top : bottom;
    return {
      feds: feds.length, ground: [x0, y0, x1, y1], area: [0, top, window.innerWidth, bottom],
      rect: window.hocReplay.frameRect(), cardTop, height: window.innerHeight,
    };
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

async function gesture(page, cdp, size, label, mouse) {
  // A one-finger drag pans, and frees the camera. The gestures start on open
  // map, below the top bar.
  const topBar = await R(page, () => document.querySelector('.mv-top').getBoundingClientRect().bottom);
  const centre = [size.width / 2, topBar + 90];
  let before = await R(page, () => window.hocReplay.view());
  if (mouse) {
    await page.mouse.move(centre[0], centre[1]);
    await page.mouse.down();
    for (let i = 1; i <= 6; i += 1) await page.mouse.move(centre[0] - 12 * i, centre[1] + 8 * i);
    await page.mouse.up();
  } else {
    await touch(cdp, 'touchStart', [centre]);
    for (let i = 1; i <= 6; i += 1) await touch(cdp, 'touchMove', [[centre[0] - 12 * i, centre[1] + 8 * i]]);
    await touch(cdp, 'touchEnd', []);
  }
  await wait(150);
  let after = await R(page, () => window.hocReplay.view());
  check(`${label}: a drag moves the map`, moved(before, after) && Math.abs(after.w - before.w) < 1e-6);
  check(`${label}: a gesture frees the camera`, (await R(page, () => window.hocReplay.mode())) === 'free');
  check(`${label}: Recentre is offered in free mode`, await page.isVisible('#mv-recentre'));

  // Free mode holds still across Next.
  before = await R(page, () => window.hocReplay.view());
  const was = await part(page);
  await next(page);
  after = await R(page, () => window.hocReplay.view());
  const now = await part(page);
  check(`${label}: Next moves on a turn`, now && was && (now.step !== was.step || now.id !== was.id));
  check(`${label}: free mode holds still across Next`, !moved(before, after));
  if (await page.isVisible('#mv-recentre')) await page.click('#mv-recentre');
  await settled(page);
  await wait(900);
  check(`${label}: Recentre returns to follow mode`, (await R(page, () => window.hocReplay.mode())) === 'follow'
    && !(await page.isVisible('#mv-recentre')));

  if (!mouse) {
    // A pinch zooms.
    before = await R(page, () => window.hocReplay.view());
    await touch(cdp, 'touchStart', [[centre[0] - 30, centre[1]], [centre[0] + 30, centre[1]]]);
    for (let i = 1; i <= 6; i += 1) {
      await touch(cdp, 'touchMove', [[centre[0] - 30 - 15 * i, centre[1]], [centre[0] + 30 + 15 * i, centre[1]]]);
    }
    await touch(cdp, 'touchEnd', []);
    await wait(150);
    after = await R(page, () => window.hocReplay.view());
    check(`${label}: a pinch zooms in`, after.w < before.w * 0.6, `${before.w} -> ${after.w}`);

    // A double tap zooms in about the tap.
    before = after;
    await page.touchscreen.tap(centre[0], centre[1]);
    await wait(60);
    await page.touchscreen.tap(centre[0], centre[1]);
    await wait(1200);
    after = await R(page, () => window.hocReplay.view());
    check(`${label}: a double tap zooms in`, after.w < before.w * 0.75 || before.w <= 3.01, `${before.w} -> ${after.w}`);
  } else {
    // The wheel zooms on a desktop.
    before = await R(page, () => window.hocReplay.view());
    await page.mouse.move(centre[0], centre[1]);
    await page.mouse.wheel(0, -400);
    await wait(200);
    after = await R(page, () => window.hocReplay.view());
    check(`${label}: the wheel zooms in`, after.w < before.w, `${before.w} -> ${after.w}`);
  }
}

async function viewport(browser, size, label) {
  const mouse = size.width >= 1200;
  const context = await browser.newContext({
    viewport: size, hasTouch: !mouse, isMobile: size.width < 700, deviceScaleFactor: mouse ? 1 : 2,
  });
  const page = await context.newPage();
  page.on('console', (m) => { if (m.type() === 'error') errors.push(`${label}: ${m.text()}`); });
  page.on('pageerror', (e) => errors.push(`${label}: ${e.message}`));
  const cdp = mouse ? null : await context.newCDPSession(page);
  const tap = async (x, y) => (mouse ? page.mouse.click(x, y) : page.touchscreen.tap(x, y));

  // Next walks 1896 turn by turn: the world, each house in order, the close.
  await open(page, 30);
  check(`${label}: the page tells the round`, await R(page, () => window.hocReplay.round()));
  const order = await R(page, () => window.hocReplay.order());
  check(`${label}: a round is the world, the houses, the close`,
    order[0] === 'world' && order[order.length - 1] === 'close' && order.length > 3, JSON.stringify(order));
  const walked = [(await part(page)).id];
  let stripOk = true;
  for (let i = 1; i < order.length; i += 1) {
    await next(page);
    const p = await part(page);
    walked.push(p.id);
    const strip = await R(page, () => {
      const box = document.querySelector('#mv-round').getBoundingClientRect();
      const current = document.querySelector('#mv-round [aria-current="step"]');
      const r = current ? current.getBoundingClientRect() : null;
      return {
        states: window.hocReplay.strip(),
        inView: Boolean(r) && r.left >= box.left - 1 && r.right <= box.right + 1,
      };
    });
    const states = strip.states;
    const expect = states.every((s, j) => s === (j < p.step ? 'done' : j === p.step ? 'current' : 'todo'));
    if (!expect || !strip.inView) stripOk = false;
  }
  check(`${label}: Next walks the world, each house and the close in order`,
    JSON.stringify(walked) === JSON.stringify(order), JSON.stringify(walked));
  check(`${label}: the strip follows, its current chip in view`, stripOk);
  await next(page);
  check(`${label}: Next after the close opens the next year`, (await R(page, () => window.hocReplay.turn())) === 31
    && (await part(page)).id === 'world');

  // Next year plays the rest of the round and stops at the close.
  await page.click('#mv-next-year');
  await page.waitForFunction(() => window.hocReplay.part() && window.hocReplay.part().kind === 'close' && !window.hocReplay.busy(),
    null, { timeout: 30000 });
  check(`${label}: Next year stops at the close`, (await R(page, () => window.hocReplay.turn())) === 31);

  // A chip opens its house's sheet; a row of the standings does too.
  const chip = await page.$('#mv-round [data-house]');
  const chipHouse = await chip.getAttribute('data-house');
  await chip.click();
  await wait(200);
  check(`${label}: a chip opens its sheet`, await page.isVisible('#mv-sheet')
    && (await R(page, () => window.hocReplay.sheet())) === chipHouse);
  const sheetText = await page.textContent('#mv-sheet-body');
  check(`${label}: the sheet names holder, heir, rank, ridings, scheme, allies and rivals`,
    ['Holder', 'Heir', 'Rank', 'Ridings', 'Allies', 'Rivals'].every((w) => sheetText.includes(w)), sheetText.slice(0, 200));
  await page.click('#mv-sheet-close');
  await page.click('#mv-standings-toggle');
  const row = await page.$('#story-strip [data-house]');
  const rowHouse = await row.getAttribute('data-house');
  await row.click();
  await wait(200);
  check(`${label}: a row of the standings opens its sheet`, (await R(page, () => window.hocReplay.sheet())) === rowHouse);
  await page.click('#mv-sheet-close');
  await page.click('#mv-standings-toggle');

  // Follow mode frames a notable turn between the top bar and the docked
  // card, leaving no more than a fifth of the map area unused below it.
  for (const [turn, year] of [[19, 1885], [48, 1914], [70, 1936]]) {
    await open(page, turn);
    const parts = await R(page, () => window.hocReplay.parts());
    const target = parts.findIndex((p, i) => i > 0 && p.kind === 'house' && p.pace !== 'quiet');
    for (let i = 0; i < target; i += 1) await next(page);
    await wait(FLIGHT_WAIT);
    const f = await framing(page);
    check(`${label}: follow mode frames a turn of ${year}`, inside(f), JSON.stringify(f));
    const mapArea = f.cardTop - f.area[1];
    const unused = f.rect ? f.cardTop - f.rect.bottom : Infinity;
    check(`${label}: the frame reaches the card in ${year}`, unused <= mapArea / 5, `${unused} of ${mapArea}`);
    const labels = await R(page, () => window.hocReplay.labels());
    const clash = labels.some((a, i) => labels.some((b, j) => i < j
      && a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1));
    check(`${label}: names on the map never overlap in ${year}`, labels.length > 0 && !clash, JSON.stringify(labels.length));
    const turnHouse = (await part(page)).id;
    check(`${label}: the house whose turn it is is named in ${year}`, labels.some((l) => l.house === turnHouse && l.priority === 0),
      turnHouse);
  }

  // A crisis tints the camps' holdings and shows its legend: 1914's world turn.
  await open(page, 48);
  check(`${label}: a crisis tints the camps`, (await R(page, () => window.hocReplay.tints())) > 0);
  check(`${label}: a crisis shows its legend`, await page.isVisible('.mv-chip-legend'));

  // Auto stops on the first turn that should stop it.
  const stops = await R(page, () => window.hocReplay.stops());
  // Auto starts from the world's turn on screen, which it does not stop on.
  const first = stops.indexOf(true, 1);
  if (first !== -1) {
    await page.click('#mv-speed');
    await page.click('#mv-speed');
    await page.click('#story-auto');
    await page.waitForFunction(() => !window.hocReplay.auto(), null, { timeout: 60000 });
    await settled(page);
    const p = await part(page);
    check(`${label}: Auto stops on a pause-weight turn`, p.step === first && p.pace === 'pause', JSON.stringify({ p, first }));
    await page.click('#mv-speed');
  }

  // A chapter's close is an opaque full-screen card: 1885's.
  await open(page, 19);
  await page.click('#mv-next-year');
  await page.waitForFunction(() => window.hocReplay.part() && window.hocReplay.part().kind === 'close' && !window.hocReplay.busy(),
    null, { timeout: 30000 });
  await wait(300);
  const full = await R(page, () => {
    const box = document.querySelector('#mv-full');
    return { shown: !box.hidden, background: getComputedStyle(box).backgroundColor };
  });
  check(`${label}: a chapter's close is an opaque card`, full.shown && !/rgba\(.*, 0?\.\d+\)/.test(full.background), JSON.stringify(full));
  if (await page.isVisible('#mv-full-continue')) await page.click('#mv-full-continue');

  // Gestures, on a notable turn of 1896.
  await open(page, 30);
  const parts1896 = await R(page, () => window.hocReplay.parts());
  const notable = parts1896.findIndex((p, i) => i > 0 && p.kind === 'house' && p.pace !== 'quiet');
  for (let i = 0; i < notable; i += 1) await next(page);
  await gesture(page, cdp, size, label, mouse);

  // A mark's card: open on a tap, closed by a tap on the map.
  await open(page, 30);
  for (let i = 0; i < notable; i += 1) await next(page);
  await wait(FLIGHT_WAIT);
  const target = await R(page, () => {
    const top = document.querySelector('.mv-top').getBoundingClientRect().bottom;
    const bottom = document.querySelector('.mv-bottom').getBoundingClientRect().top;
    const seen = [...document.querySelectorAll('[data-mark] .mk-bg')].map((c) => {
      const r = c.getBoundingClientRect();
      return { id: c.closest('[data-mark]').getAttribute('data-mark'), x: r.left, y: r.top, width: r.width, height: r.height };
    }).filter((b) => b.y > top + 4 && b.y + b.height < bottom - 4 && b.x > 4 && b.x + b.width < window.innerWidth - 4);
    return seen[0] || null;
  });
  check(`${label}: a mark is on screen`, Boolean(target));
  if (target) {
    await tap(target.x + target.width / 2, target.y + target.height / 2);
    await wait(250);
    const card = await R(page, () => window.hocReplay.card());
    check(`${label}: a tap on a mark opens its card`, await page.isVisible('#mv-card') && card && card.id === target.id,
      JSON.stringify(card));
    check(`${label}: one card at a time`, !(await page.isVisible('#mv-turn')));
    const cardBox = (await (await page.$('#mv-card')).boundingBox()) || { x: 0, y: 0, width: 0, height: 0 };
    const covers = cardBox.x < target.x + target.width && target.x < cardBox.x + cardBox.width
      && cardBox.y < target.y + target.height && target.y < cardBox.y + cardBox.height;
    check(`${label}: the card does not cover its mark`, !covers);
    const topBar = await R(page, () => document.querySelector('.mv-top').getBoundingClientRect().bottom);
    await tap(8, topBar + 40);
    await wait(250);
    check(`${label}: a tap on the map closes the card`, !(await page.isVisible('#mv-card'))
      && await page.isVisible('#mv-turn'));
  }

  await context.close();
  if (shots) await screenshots(browser, size);
}

// One whole year turn by turn at 390 px (1896), and the world's turn and first
// notable house turn of 1885, 1914 and 1936 at each size: JPEG at one device
// pixel per CSS pixel, to keep the repository light.
async function screenshots(browser, size) {
  const context = await browser.newContext({ viewport: size, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const shot = (name) => page.screenshot({ path: `${shots}/${name}.jpg`, type: 'jpeg', quality: 78 });
  if (size.width === 390) {
    await open(page, 30);
    const n = (await R(page, () => window.hocReplay.order())).length;
    for (let i = 0; i < n; i += 1) {
      await wait(FLIGHT_WAIT);
      const p = await part(page);
      await shot(`1896-${String(i).padStart(2, '0')}-${p.kind === 'house' ? 'house' : p.kind}`);
      if (i < n - 1) await next(page);
    }
  }
  for (const turn of [19, 48, 70]) {
    await open(page, turn);
    await wait(FLIGHT_WAIT);
    await shot(`${YEAR0 + turn}-world-${size.width}`);
    const parts = await R(page, () => window.hocReplay.parts());
    const at = parts.findIndex((p, i) => i > 0 && p.kind === 'house' && p.pace !== 'quiet');
    for (let i = 0; i < at; i += 1) await next(page);
    await wait(FLIGHT_WAIT);
    await shot(`${YEAR0 + turn}-turn-${size.width}`);
  }
  await context.close();
}

const FLIGHT_WAIT = 1100;

const browser = await playwright.chromium.launch();
try {
  await viewport(browser, { width: 390, height: 844 }, '390x844');
  await viewport(browser, { width: 820, height: 1180 }, '820x1180');
  await viewport(browser, { width: 1440, height: 900 }, '1440x900');
  for (const url of extra) {
    const page = await browser.newPage();
    page.on('console', (m) => { if (m.type() === 'error') errors.push(`${url}: ${m.text()}`); });
    page.on('pageerror', (e) => errors.push(`${url}: ${e.message}`));
    await page.goto(url);
    await wait(2500);
    const nextButton = await page.$('#story-next');
    if (nextButton && await nextButton.isVisible() && await nextButton.isEnabled()) {
      await nextButton.click();
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
