/* Shared helpers: api() for JSON calls and toast() for small messages */
(function () {
  'use strict';

  window.toast = function (msg) {
    var el = document.getElementById('toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(window.__toastTimer);
    window.__toastTimer = setTimeout(function () { el.classList.remove('show'); }, 2800);
  };

  // api('/api/x', {method:'POST', body:{...}}) -> resolves with JSON, rejects with Error(message)
  window.api = function (url, opts) {
    opts = opts || {};
    var init = { method: opts.method || 'GET', headers: { 'Accept': 'application/json' }, credentials: 'same-origin' };
    if (opts.body !== undefined) {
      init.method = opts.method || 'POST';
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.body);
    }
    return fetch(url, init).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (res.status === 401 && url.indexOf('/api/login') === -1 && url.indexOf('/api/google') === -1) {
          location.href = '/login';
          throw new Error('Please log in first.');
        }
        if (!res.ok) throw new Error(data.error || 'Something went wrong. Please try again.');
        return data;
      });
    }, function () {
      throw new Error('Cannot reach the server. Is it running?');
    });
  };
})();
