(function () {
  var select = document.getElementById('jump-season');
  if (!select) return;
  select.addEventListener('change', function () {
    var target = document.getElementById(select.value);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
})();
