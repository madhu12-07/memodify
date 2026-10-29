/* Detect page: pick an age group first (saved on the server), then the three ways to detect mood unlock. */
(function () {
  'use strict';
  var grid = document.getElementById('age-grid');
  var methods = document.getElementById('methods');
  var msg = document.getElementById('age-msg');
  var chosen = !!grid.querySelector('.age.selected');

  function unlock() {
    chosen = true;
    methods.classList.remove('locked');
    methods.querySelectorAll('.option').forEach(function (a) { a.removeAttribute('aria-disabled'); });
  }

  grid.addEventListener('click', function (e) {
    var b = e.target.closest('.age'); if (!b) return;
    msg.textContent = '';
    api('/api/age', { body: { age: b.dataset.age } }).then(function () {
      grid.querySelectorAll('.age').forEach(function (x) {
        var on = x === b;
        x.classList.toggle('selected', on);
        x.setAttribute('aria-checked', on ? 'true' : 'false');
      });
      unlock();
      toast('Great! Now choose how to detect your mood.');
      methods.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }).catch(function (err) { msg.textContent = err.message; });
  });

  methods.addEventListener('click', function (e) {
    if (chosen) return;
    var a = e.target.closest('.option'); if (!a) return;
    e.preventDefault();
    msg.textContent = 'Please choose your age group first.';
    grid.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
})();
