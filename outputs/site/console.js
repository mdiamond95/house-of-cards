(function () {
  // The console's whole contract with GitHub: dispatch one workflow, then watch
  // it. The token is the director's own and lives only in this browser.
  var REPO = 'mdiamond95/house-of-cards';
  var WORKFLOW = 'engine.yml';
  var API = 'https://api.github.com/repos/' + REPO;
  var POLL_MS = 10000;
  var NARRATE_TEMPLATE = "Follow CLAUDE.md. Narrate seasons {season_from}\u2013{season_to} of the live (new) scenario.{focus}\n\nTone: {tone_description}.\n\nSources, and nothing else:\n- `scenarios/new/seasons/{season_from:04d}.json` through `{season_to:04d}.json` \u2014 every roll, draw and outcome, with the purpose each was drawn for.\n- The chronicle lines already in `hoc.db` for those seasons (`events.narrative` where the event's `mechanical_delta` names one of them).\n- House detail from `hoc.db` only \u2014 house_stats, persons, objectives, holdings, relations, house_blocks. CLAUDE.md hard rule 9 applies: if a detail is not in the database, it does not go in the prose.\n\nDo not invent settlers, dates, relations, colours or events. Do not give a house a personal year it did not reach. There is no universal calendar: each house's dates are its own clock's, and two houses share a year only where the record says they met.\n\nWrite it to `narratives/{season_from:04d}-{season_to:04d}.md` with this front matter:\n\n    ---\n    seasons: {season_from}-{season_to}\n    tone: {tone}\n    ---\n\nThen run `python -m hoc export` so the chronicle picks it up, commit the narrative and `outputs/` together, push, open a PR and merge it.\n\nLength: about {words} words. Canadian spelling throughout.";
  var TONES = {"chronicle": "the measured voice of a house chronicle — third person, past tense, a paragraph to a season, more interested in consequence than incident", "intimate": "close on the people — what a holder or an heir made of the season, in their own house's idiom, without inventing anything the record does not hold", "official gazette": "the flat institutional register of a Dominion gazette — notices, appointments, grants and deaths, dated by each house's personal year"};

  function token() {
    try { return localStorage.getItem('hoc-token') || ''; } catch (e) { return ''; }
  }
  function setToken(value) {
    try {
      if (value) localStorage.setItem('hoc-token', value);
      else localStorage.removeItem('hoc-token');
    } catch (e) { /* private mode: the console still renders, just cannot remember */ }
  }

  function el(id) { return document.getElementById(id); }

  function refreshConnected() {
    var connected = !!token();
    var state = el('token-state');
    if (state) {
      state.textContent = connected
        ? 'Connected. The token is in this browser only.'
        : 'Not connected. Everything below renders; nothing can be dispatched.';
      state.className = connected ? 'meta connected' : 'meta';
    }
    Array.prototype.forEach.call(document.querySelectorAll('[data-needs-token]'), function (button) {
      button.disabled = !connected;
      button.title = connected ? '' : 'Connect a GitHub token first';
    });
  }

  function api(path, options) {
    options = options || {};
    options.headers = Object.assign({
      'Accept': 'application/vnd.github+json',
      'Authorization': 'Bearer ' + token(),
      'X-GitHub-Api-Version': '2022-11-28'
    }, options.headers || {});
    return fetch(API + path, options).then(function (response) {
      if (response.status === 204) return null;
      return response.text().then(function (text) {
        var body = null;
        try { body = text ? JSON.parse(text) : null; } catch (e) { body = null; }
        if (!response.ok) {
          var parts = ['HTTP ' + response.status];
          var needs = response.headers.get('x-accepted-github-permissions');
          var scopes = response.headers.get('x-oauth-scopes');
          if (needs) parts.push('needs: ' + needs);
          if (scopes) parts.push('token has: ' + scopes);
          if (body && body.message) parts.push(body.message);
          throw new Error(parts.join(' - '));
        }
        return body;
      });
    });
  }

  function say(box, html, kind) {
    if (!box) return;
    box.hidden = false;
    box.className = 'status-box' + (kind ? ' ' + kind : '');
    box.innerHTML = html;
  }

  // -------------------------------------------------------------- dispatch --

  function dispatch(inputs, box) {
    say(box, 'Dispatching…');
    var started = new Date().toISOString();
    return api('/actions/workflows/' + WORKFLOW + '/dispatches', {
      method: 'POST',
      body: JSON.stringify({ ref: 'main', inputs: inputs })
    }).then(function () {
      say(box, 'Dispatched. Waiting for the run to appear…');
      return watch(started, box);
    }).catch(function (error) {
      say(box, 'Could not dispatch: ' + error.message, 'bad');
    });
  }

  function watch(started, box) {
    var attempts = 0;
    function poll() {
      attempts += 1;
      api('/actions/workflows/' + WORKFLOW + '/runs?per_page=5').then(function (data) {
        var runs = (data && data.workflow_runs) || [];
        var run = runs.filter(function (r) { return r.created_at >= started; })[0] || runs[0];
        if (!run) {
          if (attempts < 30) setTimeout(poll, POLL_MS);
          return;
        }
        var link = '<a href="' + run.html_url + '" target="_blank" rel="noopener">run #' +
                   run.run_number + '</a>';
        if (run.status !== 'completed') {
          say(box, 'Running — ' + run.status.replace('_', ' ') + ' (' + link + '). ' +
                   'Checking again in ten seconds.');
          if (attempts < 180) setTimeout(poll, POLL_MS);
          return;
        }
        if (run.conclusion === 'success') {
          say(box, 'Finished (' + link + '). ' +
                   '<button type="button" onclick="location.reload()">Reload the site</button>' +
                   '<p class="footnote">The site is rebuilt by the Pages workflow a moment ' +
                   'after the engine commits, so give it a few seconds before reloading.</p>',
              'good');
        } else {
          say(box, 'The run ' + run.conclusion + ' — nothing was committed. Open ' + link +
                   ' for the summary explaining why.', 'bad');
        }
      }).catch(function (error) {
        say(box, 'Lost track of the run: ' + error.message, 'bad');
      });
    }
    setTimeout(poll, 3000);
  }

  // ------------------------------------------------------------ run seasons --

  var seasons = 10;
  Array.prototype.forEach.call(document.querySelectorAll('button.seasons'), function (button) {
    button.addEventListener('click', function () {
      seasons = Number(button.getAttribute('data-seasons'));
      Array.prototype.forEach.call(document.querySelectorAll('button.seasons'), function (other) {
        other.classList.toggle('chosen', other === button);
      });
      if (el('run-count')) el('run-count').textContent = seasons;
    });
  });

  if (el('run')) {
    el('run').addEventListener('click', function () {
      var stops = Array.prototype.slice.call(
        document.querySelectorAll('input[name=stop]:checked')
      ).map(function (box) { return box.value; });
      dispatch({
        command: 'run',
        seasons: String(seasons),
        stop_on: stops.join(','),
        note: (el('run-note') || {}).value || ''
      }, el('run-status'));
    });
  }

  // -------------------------------------------------------------- intervene --

  var pendingTurn = null;

  function fieldsOf(block) {
    var values = {};
    Array.prototype.forEach.call(block.querySelectorAll('[data-field]'), function (input) {
      values[input.getAttribute('data-field')] = input.value;
    });
    return values;
  }

  function buildTurn(op, values) {
    var operation = { op: op };
    var directive;

    if (op === 'set_objective' || op === 'veto_objective') {
      operation.house = values.house;
      operation.objective = values.objective;
      if (values.reason) operation.reason = values.reason;
      directive = (op === 'set_objective' ? 'Set ' : 'Veto ') + values.objective +
                  ' for ' + values.house + '.';
    } else if (op === 'force_action') {
      operation.house = values.house;
      operation.action = values.action;
      if (values.reason) operation.reason = values.reason;
      directive = values.house + ' is to ' + values.action + ' next season.';
    } else if (op === 'adjust_stat') {
      if (!values.reason) throw new Error('A stat adjustment needs a reason.');
      operation.house = values.house;
      operation.stat = values.stat;
      operation.delta = Number(values.delta);
      operation.reason = values.reason;
      directive = 'Adjust ' + values.house + "'s " + values.stat + ' by ' + values.delta + '.';
    } else if (op === 'grant_house') {
      // The engine names the house from the community banks and gives it its
      // colours, holder and opening stats; a surname here fixes only the
      // surname, and is still checked against the denylist.
      operation.riding = values.riding;
      operation.community = values.community;
      operation.rank = values.rank;
      operation.tag = values.tag;
      if (values.surname) operation.surname = values.surname;
      if (values.reason) operation.reason = values.reason;
      directive = 'Grant a ' + values.rank + ' seated at ' + values.riding + '.';
    } else if (op === 'set_clock') {
      if (!values.basis) throw new Error('Setting a clock needs a basis.');
      operation.house = values.house;
      operation.personal_year = Number(values.personal_year);
      operation.basis = values.basis;
      directive = values.house + "'s clock is set to " + values.personal_year + '.';
    } else if (op === 'relation') {
      if (values.house_a === values.house_b) throw new Error('A house cannot relate to itself.');
      if (!values.text) throw new Error('A relation needs its text.');
      operation.house_a = values.house_a;
      operation.house_b = values.house_b;
      operation.marker = values.marker;
      operation.text = values.text;
      directive = values.house_a + ' and ' + values.house_b + ': ' + values.marker + '.';
    }

    return {
      directive: directive,
      event: {
        kind: 'other',
        title: "Director's intervention",
        narrative: directive,
        houses: []
      },
      operations: [operation]
    };
  }

  Array.prototype.forEach.call(document.querySelectorAll('.intervention .build'), function (button) {
    button.addEventListener('click', function () {
      var block = button.closest('.intervention');
      var op = block.getAttribute('data-op');
      try {
        pendingTurn = buildTurn(op, fieldsOf(block));
      } catch (error) {
        say(el('intervene-status'), error.message, 'bad');
        return;
      }
      el('turn-json').textContent = JSON.stringify(pendingTurn, null, 2);
      el('turn-review').hidden = false;
      el('turn-review').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  });

  if (el('cancel-turn')) {
    el('cancel-turn').addEventListener('click', function () {
      pendingTurn = null;
      el('turn-review').hidden = true;
    });
  }

  if (el('dispatch-turn')) {
    el('dispatch-turn').addEventListener('click', function () {
      if (!pendingTurn) return;
      dispatch({
        command: 'intervene',
        payload: JSON.stringify(pendingTurn),
        note: pendingTurn.directive
      }, el('intervene-status'));
      el('turn-review').hidden = true;
    });
  }

  // ------------------------------------------------------------------ rules --

  var rulesLoaded = {};

  function numericFields(prefix, value, into) {
    Object.keys(value).forEach(function (key) {
      var child = value[key];
      var path = prefix ? prefix + '.' + key : key;
      if (typeof child === 'number') into[path] = child;
      else if (child && typeof child === 'object' && !Array.isArray(child)) {
        numericFields(path, child, into);
      }
    });
    return into;
  }

  function renderRules(file, fields) {
    var rows = Object.keys(fields).sort().map(function (path) {
      var id = 'rule--' + file + '--' + path;
      return '<div class="field rule"><label for="' + id + '">' + path + '</label>' +
             '<input id="' + id + '" type="number" step="any" data-file="' + file + '"' +
             ' data-path="' + path + '" data-original="' + fields[path] + '"' +
             ' value="' + fields[path] + '"></div>';
    }).join('');
    return '<details><summary>' + file + '</summary>' + rows + '</details>';
  }

  if (el('load-rules')) {
    el('load-rules').addEventListener('click', function () {
      var box = el('rules-fields');
      box.innerHTML = 'Loading…';
      var files = ['friction.json', 'founding.json', 'succession.json', 'responses.json'];
      Promise.all(files.map(function (name) {
        return api('/contents/rules/' + name).then(function (data) {
          return { name: name, body: JSON.parse(atob(data.content.replace(/\n/g, ''))) };
        });
      })).then(function (loaded) {
        box.innerHTML = loaded.map(function (entry) {
          var fields = numericFields('', entry.body, {});
          rulesLoaded[entry.name] = fields;
          return renderRules(entry.name, fields);
        }).join('');
      }).catch(function (error) {
        box.innerHTML = '<p class="bad">Could not read the rules: ' + error.message + '</p>';
      });
    });
  }

  if (el('propose-rules')) {
    el('propose-rules').addEventListener('click', function () {
      var note = (el('rules-note') || {}).value || '';
      if (!note.trim()) {
        say(el('rules-status'), 'A rules change needs a note saying what you observed.', 'bad');
        return;
      }
      var patch = {};
      var diff = [];
      Array.prototype.forEach.call(document.querySelectorAll('input[data-path]'), function (input) {
        var before = Number(input.getAttribute('data-original'));
        var after = Number(input.value);
        if (after === before) return;
        var file = input.getAttribute('data-file');
        patch[file] = patch[file] || {};
        patch[file][input.getAttribute('data-path')] = after;
        diff.push(file + ':' + input.getAttribute('data-path') + '  ' + before + ' → ' + after);
      });
      if (!diff.length) {
        say(el('rules-status'), 'Nothing changed.', 'bad');
        return;
      }
      el('rules-diff').hidden = false;
      el('rules-diff').textContent = diff.join('\n');
      dispatch({ command: 'rules', payload: JSON.stringify(patch), note: note },
               el('rules-status'));
    });
  }

  // --------------------------------------------------------------- narrate --

  if (el('build-narrate')) {
    el('build-narrate').addEventListener('click', function () {
      var from = Number(el('narrate-from').value);
      var to = Number(el('narrate-to').value);
      if (to < from) { var swap = from; from = to; to = swap; }
      var houses = (el('narrate-houses').value || '').split(',')
        .map(function (name) { return name.trim(); })
        .filter(Boolean);
      var focus = '';
      if (houses.length === 1) {
        focus = ' Focus on ' + houses[0] +
                ', and mention other houses only where they touch these.';
      } else if (houses.length > 1) {
        focus = ' Focus on ' + houses.slice(0, -1).join(', ') + ' and ' +
                houses[houses.length - 1] +
                ', and mention other houses only where they touch these.';
      }
      var tone = el('narrate-tone').value;
      var span = to - from + 1;
      var words = Math.max(300, Math.min(1200, span * 120));
      function pad(n) { return String(n).padStart(4, '0'); }

      var block = NARRATE_TEMPLATE
        .replace(/\{season_from:04d\}/g, pad(from))
        .replace(/\{season_to:04d\}/g, pad(to))
        .replace(/\{season_from\}/g, from)
        .replace(/\{season_to\}/g, to)
        .replace(/\{focus\}/g, focus)
        .replace(/\{tone_description\}/g, TONES[tone])
        .replace(/\{tone\}/g, tone)
        .replace(/\{words\}/g, words);

      el('narrate-block').hidden = false;
      el('narrate-block').textContent = block;
    });
  }

  if (el('copy-narrate')) {
    el('copy-narrate').addEventListener('click', function () {
      var text = el('narrate-block').textContent;
      if (!text) return;
      navigator.clipboard.writeText(text).then(function () {
        el('copy-narrate').textContent = 'Copied';
        setTimeout(function () { el('copy-narrate').textContent = 'Copy'; }, 2000);
      });
    });
  }

  // -------------------------------------------------------- rebuild, status --

  if (el('rebuild')) {
    el('rebuild').addEventListener('click', function () {
      dispatch({ command: 'rebuild', note: 'verify the record reproduces the database' },
               el('rebuild-status'));
    });
  }

  function listRuns() {
    if (!token()) return;
    api('/actions/workflows/' + WORKFLOW + '/runs?per_page=10').then(function (data) {
      var runs = (data && data.workflow_runs) || [];
      if (!runs.length) { el('runs').textContent = 'No engine run yet.'; return; }
      el('runs').innerHTML = '<ul class="runs">' + runs.map(function (run) {
        var state = run.status === 'completed' ? (run.conclusion || '') : run.status;
        return '<li><a href="' + run.html_url + '" target="_blank" rel="noopener">#' +
               run.run_number + '</a> <span class="meta">' + run.display_title +
               ' — ' + state + '</span></li>';
      }).join('') + '</ul>';
    }).catch(function (error) {
      el('runs').textContent = 'Could not list runs: ' + error.message;
    });
  }

  // ------------------------------------------------------------------ wire --

  if (el('connect')) {
    el('connect').addEventListener('click', function () {
      var value = (el('token').value || '').trim();
      if (!value) {
        // Never read an empty field as an instruction to forget the token:
        // that is what Disconnect is for, and it is one click away.
        var state = el('token-state');
        if (state) {
          state.textContent = 'Paste a token first.';
          state.className = 'meta bad';
        }
        el('token').focus();
        return;
      }
      setToken(value);
      el('token').value = '';
      refreshConnected();
      listRuns();
    });
  }
  if (el('disconnect')) {
    el('disconnect').addEventListener('click', function () {
      setToken('');
      refreshConnected();
      el('runs').textContent = 'Connect to list the engine\'s recent runs.';
    });
  }
  if (el('check-token')) {
    el('check-token').addEventListener('click', function () {
      var box = el('check-token-status');
      say(box, 'Checking…');
      // A direct fetch, not api(): the check needs the x-oauth-scopes header
      // as well as the body, and api() only ever hands callers the body.
      fetch(API, {
        headers: {
          'Accept': 'application/vnd.github+json',
          'Authorization': 'Bearer ' + token(),
          'X-GitHub-Api-Version': '2022-11-28'
        }
      }).then(function (response) {
        var scopes = response.headers.get('x-oauth-scopes') || '(none reported)';
        return response.json().then(function (body) {
          if (!response.ok) {
            throw new Error('HTTP ' + response.status + ' - ' + ((body && body.message) || 'could not read the repository'));
          }
          var perms = body.permissions || {};
          var permList = Object.keys(perms).filter(function (key) { return perms[key]; });
          say(box,
              '<p>Repository permissions: ' + (permList.length ? permList.join(', ') : '(none)') + '</p>' +
              '<p>Token scopes: ' + scopes + '</p>',
              'good');
        });
      }).catch(function (error) {
        say(box, 'Could not check the token: ' + error.message, 'bad');
      });
    });
  }

  refreshConnected();
  listRuns();
})();
