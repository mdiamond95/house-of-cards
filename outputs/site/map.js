(function () {
  var map = document.getElementById('map');
  var panel = document.getElementById('panel');
  var body = document.getElementById('panel-body');
  var close = document.getElementById('panel-close');
  if (!map || !panel || !body || !close) return;

  function show(path) {
    var house = path.getAttribute('data-house');
    var holder = path.getAttribute('data-holder');
    var seat = path.getAttribute('data-seat');
    var slug = path.getAttribute('data-slug');
    var rows = [
      '<h3>' + path.getAttribute('data-riding') + '</h3>',
      '<p class="panel-meta">' + path.getAttribute('data-province') + '</p>'
    ];
    if (house) {
      rows.push('<p><a href="houses/' + slug + '.html">' + house + '</a>' +
                (seat ? ' &middot; seat ' + seat : '') + '</p>');
      rows.push('<p class="panel-meta">' + (holder || 'holder not recovered') + '</p>');
    } else {
      rows.push('<p class="panel-meta">Unclaimed</p>');
    }
    body.innerHTML = rows.join('');
    panel.hidden = false;
  }

  map.addEventListener('click', function (event) {
    var path = event.target.closest('path');
    if (path) show(path);
  });
  close.addEventListener('click', function () { panel.hidden = true; });

  var toggle = document.getElementById('view-toggle');
  var borders = document.getElementById('map-borders');
  if (toggle) {
    var showingSouth = true;
    toggle.addEventListener('click', function () {
      showingSouth = !showingSouth;
      map.setAttribute('viewBox', map.getAttribute(showingSouth ? 'data-view-south' : 'data-view-full'));
      if (borders) {
        borders.setAttribute('stroke-width', map.getAttribute(showingSouth ? 'data-stroke-south' : 'data-stroke-full'));
      }
      toggle.textContent = showingSouth ? 'Show the north' : 'Show the south';
    });
  }

  // ---------------------------------------------------------- the scrubber --
  //
  // The site is static, so the whole history arrives as one file and the
  // browser replays it. timeline.json holds a diff per season — only the
  // ridings that changed hands — so walking to season N means applying every
  // frame up to N, which is cheap enough to do on every drag of the slider.

  var slider = document.getElementById('season');
  if (!slider) return;

  var label = document.getElementById('season-label');
  var play = document.getElementById('play');
  var legend = document.getElementById('legend');
  var strip = document.querySelector('.status');
  var paths = Array.prototype.slice.call(map.querySelectorAll('path[data-riding]'));
  var byRiding = {};
  paths.forEach(function (path) {
    var fed = path.getAttribute('data-fed');
    if (fed) byRiding[fed] = path;
  });

  var timeline = null;
  var UNCLAIMED = '#e8e4dc';

  function ownersAt(season) {
    var owners = {};
    var frames = Object.keys(timeline.changes).map(Number).sort(function (a, b) { return a - b; });
    for (var i = 0; i < frames.length; i++) {
      if (frames[i] > season) break;
      var frame = timeline.changes[String(frames[i])];
      for (var fed in frame) owners[fed] = frame[fed];
    }
    return owners;
  }

  function paint(season) {
    var owners = ownersAt(season);
    var counts = {};
    for (var fed in byRiding) {
      var house = owners[fed] || null;
      var info = house ? timeline.houses[house] : null;
      byRiding[fed].setAttribute('fill', (info && info.primary) || UNCLAIMED);
      byRiding[fed].setAttribute('data-house', house || '');
      if (house) counts[house] = (counts[house] || 0) + 1;
    }

    if (label) label.textContent = 'season ' + season;

    var tally = timeline.counts[String(season)];
    if (strip && tally) {
      var stats = strip.querySelectorAll('.stat b');
      if (stats.length > 1) stats[1].textContent = tally[0];
      if (stats.length > 3) stats[3].textContent = tally[1];
    }

    if (legend) {
      var names = Object.keys(counts).sort(function (a, b) {
        return counts[b] - counts[a] || (a < b ? -1 : 1);
      });
      legend.innerHTML = names.map(function (name) {
        var info = timeline.houses[name] || {};
        return '<li><a href="houses/' + slugOf(name) + '.html">' +
               '<span class="swatch" style="background:' + (info.primary || UNCLAIMED) + '"></span>' +
               '<span class="legend-name">' + name + '</span>' +
               '<span class="legend-count">' + counts[name] + '</span></a></li>';
      }).join('');
    }
  }

  var slugs = {};
  paths.forEach(function (path) {
    var house = path.getAttribute('data-house');
    var slug = path.getAttribute('data-slug');
    if (house && slug) slugs[house] = slug;
  });
  function slugOf(name) {
    return slugs[name] || name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  }

  fetch('data/timeline.json').then(function (response) {
    return response.json();
  }).then(function (data) {
    timeline = data;
    Object.keys(data.houses).forEach(function (name) {
      if (!slugs[name]) {
        slugs[name] = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      }
    });
    slider.disabled = false;
    slider.addEventListener('input', function () { paint(Number(slider.value)); });
  }).catch(function () {
    // No timeline (or opened from the filesystem): leave the map on the
    // season it was rendered at rather than blanking it.
    slider.disabled = true;
    if (label) label.textContent = 'history unavailable';
  });

  var timer = null;
  var SEASONS_PER_SECOND = 4;
  if (play) {
    play.addEventListener('click', function () {
      if (timer) {
        clearInterval(timer);
        timer = null;
        play.textContent = 'Play';
        return;
      }
      if (!timeline) return;
      if (Number(slider.value) >= Number(slider.max)) slider.value = slider.min;
      play.textContent = 'Pause';
      timer = setInterval(function () {
        var next = Number(slider.value) + 1;
        if (next > Number(slider.max)) {
          clearInterval(timer);
          timer = null;
          play.textContent = 'Play';
          return;
        }
        slider.value = next;
        paint(next);
      }, 1000 / SEASONS_PER_SECOND);
    });
  }
})();
