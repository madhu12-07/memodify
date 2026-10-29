/* Login / Sign up tabs + Google sign-in */
(function () {
  'use strict';
  var mode = 'login';
  var form = document.getElementById('auth-form');
  var msg = document.getElementById('form-msg');
  var btn = document.getElementById('submit-btn');
  var nameField = document.getElementById('name-field');
  var pw = document.getElementById('password');

  function setMode(m) {
    mode = m;
    document.getElementById('tab-login').classList.toggle('active', m === 'login');
    document.getElementById('tab-signup').classList.toggle('active', m === 'signup');
    nameField.classList.toggle('hidden', m === 'login');
    btn.textContent = m === 'login' ? 'Log in' : 'Create account';
    pw.autocomplete = m === 'login' ? 'current-password' : 'new-password';
    msg.textContent = '';
  }
  document.getElementById('tab-login').addEventListener('click', function () { setMode('login'); });
  document.getElementById('tab-signup').addEventListener('click', function () { setMode('signup'); });

  document.getElementById('toggle-pw').addEventListener('click', function () {
    pw.type = pw.type === 'password' ? 'text' : 'password';
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    msg.textContent = '';
    // NOTE: form.name is the form's own "name" attribute, so read inputs by id
    var body = { email: document.getElementById('email').value.trim(), password: pw.value };
    if (mode === 'signup') body.name = document.getElementById('name').value.trim();
    btn.disabled = true;
    api(mode === 'login' ? '/api/login' : '/api/signup', { body: body })
      .then(function (d) { location.href = d.redirect || '/home'; })
      .catch(function (err) { msg.textContent = err.message; btn.disabled = false; });
  });

  // ---- Google sign-in (Google Identity Services) ----
  var holder = document.getElementById('google-btn');
  var missing = document.getElementById('google-missing');
  if (missing) {
    missing.addEventListener('click', function () {
      msg.textContent = 'Google sign-in is not set up yet. Add GOOGLE_CLIENT_ID in the .env file (see README).';
    });
  }
  if (holder) {
    var s = document.createElement('script');
    s.src = 'https://accounts.google.com/gsi/client';
    s.async = true; s.defer = true;
    s.onload = function () {
      google.accounts.id.initialize({
        client_id: holder.dataset.clientId,
        callback: function (resp) {
          api('/api/google', { body: { credential: resp.credential } })
            .then(function (d) { location.href = d.redirect || '/home'; })
            .catch(function (err) { msg.textContent = err.message; });
        }
      });
      google.accounts.id.renderButton(holder, { theme: 'filled_black', size: 'large', shape: 'pill', text: 'continue_with', width: 340 });
    };
    s.onerror = function () { msg.textContent = 'Could not load Google sign-in. Check your internet connection.'; };
    document.head.appendChild(s);
  }
})();
