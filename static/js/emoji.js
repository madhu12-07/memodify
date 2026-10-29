/* Emoji mood picker */
(function () {
  'use strict';
  var grid = document.getElementById('emoji-grid');
  var go = document.getElementById('go-btn');
  var msg = document.getElementById('emoji-msg');
  var selected = null;

  api('/api/emojis').then(function (d) {
    d.emojis.forEach(function (e) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'emoji-btn';
      b.setAttribute('role', 'option');
      b.setAttribute('aria-label', e.label);
      var big = document.createElement('span'); big.className = 'e'; big.textContent = e.emoji;
      var name = document.createElement('b'); name.textContent = e.label;
      b.appendChild(big); b.appendChild(name);
      b.addEventListener('click', function () {
        selected = e.emoji;
        grid.querySelectorAll('.emoji-btn').forEach(function (x) { x.classList.remove('selected'); });
        b.classList.add('selected');
        go.disabled = false;
      });
      grid.appendChild(b);
    });
  }).catch(function (e) { msg.textContent = e.message; });

  go.addEventListener('click', function () {
    if (!selected) return;
    go.disabled = true;
    api('/api/recommend', { body: { source: 'emoji', emoji: selected } })
      .then(function (d) { location.href = d.redirect; })
      .catch(function (e) { msg.textContent = e.message; go.disabled = false; });
  });
})();
