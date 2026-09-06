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
})();
