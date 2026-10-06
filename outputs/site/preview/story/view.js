// What the replay page and the play page share in showing a dispatch: the
// dispatch and the standings strip as HTML, the map camera that zooms to a
// headline and back, and the remembered choice of house to follow.
//
// The HTML builders and the box arithmetic are pure and run under node; the
// camera and the stored choice touch the page and are written to fail quietly —
// a page without localStorage, or without requestAnimationFrame, still works.

export function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ----------------------------------------------------------- following ----

// The followed house, by key, or null. localStorage can be missing, blocked or
// throwing (a private window, a sandboxed frame); following then lasts only as
// long as the page.
export function readStored(key, storage = globalThis.localStorage) {
  try {
    const value = storage ? storage.getItem(key) : null;
    return value || null;
  } catch (error) {
    return null;
  }
}

export function writeStored(key, value, storage = globalThis.localStorage) {
  try {
    if (!storage) return false;
    if (value) storage.setItem(key, value);
    else storage.removeItem(key);
    return true;
  } catch (error) {
    return false;
  }
}

// ---------------------------------------------------------------- HTML ----

const ARROWS = { up: '▲', down: '▼', same: '–', new: '★' };
const MOVES = { up: 'up', down: 'down', same: 'no change', new: 'new to the top eight' };

// The standings strip (§3.3): the top eight with movement since last turn.
export function stripHtml(rows, { nameOf = (h) => h, colourOf = () => null, follow = null } = {}) {
  return rows.map((row) => {
    const colour = colourOf(row.house) || '#bbb';
    const was = row.was === null ? '' : ` (was ${row.was})`;
    return `<li class="standing move-${row.move}${row.house === follow ? ' followed' : ''}">`
      + `<span class="standing-place">${row.place}</span>`
      + `<span class="standing-move" title="${MOVES[row.move]}${was}" aria-label="${MOVES[row.move]}${was}">${ARROWS[row.move]}</span>`
      + `<span class="swatch" style="background:${escapeHtml(colour)}"></span>`
      + `<span class="standing-name">${escapeHtml(nameOf(row.house))}</span>`
      + `<span class="standing-score">${row.score}</span></li>`;
  }).join('');
}

const CHANGES = { opened: 'opens', climax: 'reaches its climax', closed: 'closes' };

// One dispatch (§3.2) as HTML: the heading, then a headline — with its
// storyline's kicker, the storyline's other beats this turn and its previous
// beat — up to three secondary beats and a ledger line; or the one quiet-turn
// line.
export function dispatchHtml(d, { unit = 'season' } = {}) {
  const word = unit === 'turn' ? 'Turn' : 'Season';
  const heading = `<h2 class="dispatch-turn">${word} ${d.turn}</h2>`;
  if (d.quiet) return `${heading}<p class="dispatch-quiet">${escapeHtml(d.quietLine)}</p>`;
  const kind = d.headline.beat.kind.replace(/_/g, ' ');
  const kicker = d.kicker
    ? `<p class="dispatch-kicker" data-storyline="${escapeHtml(d.kicker.id)}">${escapeHtml(d.kicker.text)}</p>`
    : '';
  const related = d.related && d.related.length
    ? `<ul class="dispatch-related">${d.related.map((r) => `<li>${escapeHtml(r.text)}</li>`).join('')}</ul>`
    : '';
  const previously = d.previously
    ? `<p class="dispatch-previously">Previously, ${unit === 'turn' ? 'turn' : 'season'} ${d.previously.turn}: ${escapeHtml(d.previously.text)}</p>`
    : '';
  const secondary = d.secondary.length
    ? `<ul class="dispatch-secondary">${d.secondary.map((s) => `<li>${escapeHtml(s.text)}</li>`).join('')}</ul>`
    : '';
  const ledger = d.ledger ? `<p class="dispatch-ledger">${escapeHtml(d.ledger)}</p>` : '';
  const moments = d.moments && d.moments.length
    ? `<p class="dispatch-moments meta">${d.moments.map((m) => `${escapeHtml(m.name)} ${CHANGES[m.change] || m.change}`).join('; ')}.</p>`
    : '';
  return `${heading}${kicker}<p class="dispatch-headline${d.pause ? ' pause' : ''}">${escapeHtml(d.headline.text)}</p>`
    + `<p class="dispatch-kind meta">${escapeHtml(kind)} &middot; weight ${d.headline.weight}</p>`
    + related + previously + secondary + ledger + moments;
}

// Why Auto stopped on this dispatch, or null.
export function pauseReason(d) {
  if (!d || !d.pause) return null;
  return `Paused: ${(d.stops || []).join('; ')}. Press Auto to carry on.`;
}

export function recordHtml(d) {
  return d.record.length
    ? d.record.map((line) => `<li>${escapeHtml(line)}</li>`).join('')
    : '<li class="meta">Nothing was written this turn.</li>';
}

function storylineMeta(s, unit) {
  const word = unit === 'turn' ? 'turn' : 'season';
  const span = s.closed === null || s.closed === undefined
    ? `since ${word} ${s.opened}` : `${word}s ${s.opened}–${s.closed}`;
  const state = s.state === 'closed' ? (s.outcome || 'closed') : s.state;
  const n = Array.isArray(s.beats) ? s.beats.length : s.beats;
  return `${escapeHtml(state)} &middot; ${n} beat${n === 1 ? '' : 's'} &middot; ${span}`;
}

// The Afoot panel (§3.4): open storylines, as buttons that show their beats.
export function afootHtml(list, { unit = 'season', selected = null } = {}) {
  if (!list.length) return '<li class="meta">Nothing is afoot yet.</li>';
  return list.map((s) => `<li><button type="button" class="afoot-item${s.id === selected ? ' chosen' : ''}"`
    + ` data-storyline="${escapeHtml(s.id)}"><span class="afoot-name">${escapeHtml(s.name)}</span>`
    + `<span class="afoot-meta meta">${storylineMeta(s, unit)}</span></button></li>`).join('');
}

// The Plans afoot panel (Phase C2): every public scheme of a cast or followed
// house (dispatch.js Story.plansAfoot), with its target and turns remaining.
export function plansHtml(list, { unit = 'season' } = {}) {
  if (!list || !list.length) return '<li class="meta">No scheme of the cast is afoot.</li>';
  const word = unit === 'turn' ? 'turn' : 'season';
  return list.map((p) => {
    const aim = [p.target, p.riding].filter(Boolean).join(', ');
    const left = p.turnsRemaining === 1 ? `resolves next ${word}` : `${p.turnsRemaining} ${word}s to run`;
    return `<li class="plan${p.followed ? ' followed' : ''}"><span class="plan-house">${escapeHtml(p.name)}</span>`
      + ` <span class="plan-scheme">${escapeHtml(p.scheme)}</span>`
      + (aim ? ` <span class="plan-target">&rarr; ${escapeHtml(aim)}</span>` : '')
      + ` <span class="plan-left meta">${escapeHtml(left)}</span></li>`;
  }).join('');
}

// A storyline told top to bottom (dispatch.js Story.tell): its beats with
// their turns, then how it ended. `link(turn)` gives a link for a beat's turn.
export function storylineHtml(told, { unit = 'season', link = null } = {}) {
  const word = unit === 'turn' ? 'Turn' : 'Season';
  const beats = told.beats.map((b) => {
    const when = link ? `<a href="${escapeHtml(link(b.turn))}">${word} ${b.turn}</a>` : `${word} ${b.turn}`;
    return `<li><span class="storyline-turn">${when}</span> ${escapeHtml(b.text)}</li>`;
  }).join('');
  const end = told.state === 'closed'
    ? `<p class="storyline-outcome">Closed ${word.toLowerCase()} ${told.closed}: ${escapeHtml(told.outcome || 'closed')}.</p>`
    : `<p class="storyline-outcome meta">Still ${told.state === 'climax' ? 'at its climax' : 'rising'}.</p>`;
  return `<h3 class="storyline-name">${escapeHtml(told.name)}</h3>`
    + `<p class="meta">${storylineMeta(told, unit)}</p>`
    + `<ol class="storyline-beats">${beats || '<li class="meta">No beat yet.</li>'}</ol>${end}`;
}

// ----------------------------------------------------------------- boxes ----

export function parseBox(text) {
  return String(text).trim().split(/[\s,]+/).map(Number);
}

export function formatBox(box) {
  return box.map((n) => n.toFixed(1)).join(' ');
}

// The box to zoom to around `bounds` [x, y, w, h]: padded on every side, no
// narrower than `minFraction` of `home`, and in `home`'s aspect ratio so the
// map neither stretches nor jumps in height.
export function focusBox(bounds, home, { pad = 0.5, minFraction = 0.12 } = {}) {
  const [hx, hy, hw, hh] = home;
  const aspect = hh / hw;
  let w = Math.max(bounds[2] * (1 + 2 * pad), hw * minFraction);
  let h = Math.max(bounds[3] * (1 + 2 * pad), w * aspect);
  w = Math.max(w, h / aspect);
  h = w * aspect;
  if (w >= hw) return [...home];
  const cx = bounds[0] + bounds[2] / 2;
  const cy = bounds[1] + bounds[3] / 2;
  const x = Math.min(Math.max(cx - w / 2, hx), hx + hw - w);
  const y = Math.min(Math.max(cy - h / 2, hy), hy + hh - h);
  return [x, y, w, h];
}

export function unionBox(boxes) {
  if (!boxes.length) return null;
  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity;
  for (const [x, y, w, h] of boxes) {
    x0 = Math.min(x0, x); y0 = Math.min(y0, y);
    x1 = Math.max(x1, x + w); y1 = Math.max(y1, y + h);
  }
  return [x0, y0, x1 - x0, y1 - y0];
}

export function lerpBox(a, b, t) {
  return a.map((v, i) => v + (b[i] - v) * t);
}

// ---------------------------------------------------------------- camera ----

// Zooms the map to a set of ridings and, after `hold` ms, back to where it was.
// The borders path is drawn in map units, so its stroke is scaled with the zoom
// to keep the same width on screen.
export class MapCamera {
  constructor(svg, { borders = null, duration = 450, hold = 1800 } = {}) {
    this.svg = svg;
    this.borders = borders;
    this.duration = duration;
    this.hold = hold;
    this.home = null;
    this.homeText = null;
    this.homeStroke = null;
    this.timer = null;
    this.frame = null;
  }

  pathFor(fed) {
    return this.svg.querySelector(`path[data-fed="${fed}"]`);
  }

  boundsOf(feds) {
    const boxes = [];
    for (const fed of feds) {
      const path = this.pathFor(fed);
      if (!path || typeof path.getBBox !== 'function') continue;
      const b = path.getBBox();
      if (b.width || b.height) boxes.push([b.x, b.y, b.width, b.height]);
    }
    return unionBox(boxes);
  }

  focus(feds) {
    if (!this.svg || !feds || !feds.length) return false;
    const bounds = this.boundsOf(feds);
    if (!bounds) return false;
    if (this.home === null) {
      // The attribute exactly as it was, so a page comparing it with its own
      // data-view-* strings still recognises its view once the camera is back.
      this.homeText = this.svg.getAttribute('viewBox');
      this.home = parseBox(this.homeText);
      this.homeStroke = this.borders ? Number(this.borders.getAttribute('stroke-width')) : null;
    }
    if (this.timer !== null) clearTimeout(this.timer);
    this.animate(focusBox(bounds, this.home));
    this.timer = setTimeout(() => this.back(), this.hold);
    return true;
  }

  back() {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    if (this.home === null) return;
    const home = this.home;
    this.animate(home, () => this.restore());
  }

  // Straight back to where the camera found the map, with no animation: for
  // a control (the north/south toggle) that is about to set the view itself.
  reset() {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    if (this.frame !== null && globalThis.cancelAnimationFrame) globalThis.cancelAnimationFrame(this.frame);
    this.frame = null;
    if (this.home !== null) this.restore();
  }

  restore() {
    this.svg.setAttribute('viewBox', this.homeText);
    if (this.borders && this.homeStroke !== null) {
      this.borders.setAttribute('stroke-width', String(this.homeStroke));
    }
    this.home = null;
    this.homeText = null;
  }

  set(box) {
    this.svg.setAttribute('viewBox', formatBox(box));
    if (this.borders && this.homeStroke !== null && this.home !== null) {
      this.borders.setAttribute('stroke-width', (this.homeStroke * box[2] / this.home[2]).toFixed(4));
    }
  }

  animate(target, done = null) {
    const from = parseBox(this.svg.getAttribute('viewBox'));
    const raf = globalThis.requestAnimationFrame;
    if (this.frame !== null && globalThis.cancelAnimationFrame) globalThis.cancelAnimationFrame(this.frame);
    if (typeof raf !== 'function' || this.duration <= 0) {
      this.set(target);
      if (done) done();
      return;
    }
    const start = globalThis.performance ? performance.now() : Date.now();
    const stepFrame = (now) => {
      const t = Math.min(1, (now - start) / this.duration);
      const eased = t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2;
      this.set(lerpBox(from, target, eased));
      if (t < 1) this.frame = raf(stepFrame);
      else {
        this.frame = null;
        if (done) done();
      }
    };
    this.frame = raf(stepFrame);
  }
}
