/* Song list (Results + Favorites): play button (plays inside the page via player.js), lyrics pop-up, favorite heart. */
(function () {
  'use strict';

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  // ---------------- lyrics modal ----------------
  var modal = null;
  function closeModal() { if (modal) { modal.remove(); modal = null; document.removeEventListener('keydown', onKey); } }
  function onKey(e) { if (e.key === 'Escape') closeModal(); }

  function openLyrics(song) {
    closeModal();
    modal = el('div', 'modal');
    modal.setAttribute('role', 'dialog'); modal.setAttribute('aria-modal', 'true'); modal.setAttribute('aria-label', 'Lyrics of ' + song.title);
    var box = el('div', 'modal-box card');
    var head = el('div', 'row'); head.style.justifyContent = 'space-between'; head.style.alignItems = 'flex-start';
    var t = el('div'); t.appendChild(el('h2', '', song.title));
    t.appendChild(el('p', 'muted small', [song.movie, song.year, song.music_director].filter(Boolean).join(' · ')));
    head.appendChild(t);
    var x = el('button', 'icon-btn', '✕'); x.type = 'button'; x.setAttribute('aria-label', 'Close'); x.addEventListener('click', closeModal);
    head.appendChild(x); box.appendChild(head);

    var seg = el('div', 'seg');
    var bT = el('button', 'seg-btn selected', 'Tamil'); bT.type = 'button';
    var bE = el('button', 'seg-btn', 'Transliteration'); bE.type = 'button';
    seg.appendChild(bT); seg.appendChild(bE); box.appendChild(seg);
    var pre = el('pre', '', 'Loading…'); pre.tabIndex = 0; box.appendChild(pre);
    modal.appendChild(box); document.body.appendChild(modal);
    modal.addEventListener('click', function (e) { if (e.target === modal) closeModal(); });
    document.addEventListener('keydown', onKey);
    x.focus();

    var data = { tamil: '', english: '' };
    function show(lang) {
      pre.textContent = data[lang] || data.tamil || data.english || 'Lyrics not available for this song.';
      pre.scrollTop = 0; bT.classList.toggle('selected', lang === 'tamil'); bE.classList.toggle('selected', lang === 'english');
    }
    bT.addEventListener('click', function () { show('tamil'); });
    bE.addEventListener('click', function () { show('english'); });
    api('/api/lyrics/' + song.id).then(function (d) { data = d; show('tamil'); })
      .catch(function (e) { pre.textContent = e.message; });
  }

  // ---------------- rows ----------------
  function buildRow(song, opts, list) {
    var row = el('article', 'song');
    row.dataset.id = song.id;
    var cover = el('button', 'cover', '🎵'); cover.type = 'button'; cover.title = 'Play'; cover.setAttribute('aria-hidden', 'true'); cover.tabIndex = -1;
    cover.addEventListener('click', function () { if (window.Player) Player.play(song, list); });
    row.appendChild(cover);

    var info = el('div');
    info.appendChild(el('h3', '', song.title));
    info.appendChild(el('p', '', [song.movie, song.year, song.music_director].filter(Boolean).join(' · ')));
    row.appendChild(info);

    var acts = el('div', 'actions');
    var play = el('button', 'icon-btn play', '▶'); play.type = 'button'; play.title = 'Play';
    play.setAttribute('aria-label', 'Play ' + song.title);
    play.addEventListener('click', function () {
      if (window.Player) Player.play(song, list); else toast('The player could not load. Please refresh the page.');
    });
    acts.appendChild(play);

    var ly = el('button', 'icon-btn', '📖'); ly.type = 'button'; ly.title = 'Lyrics'; ly.setAttribute('aria-label', 'Lyrics of ' + song.title);
    if (song.has_lyrics === false) { ly.classList.add('dim'); ly.title = 'Lyrics not available for this song'; }
    ly.addEventListener('click', function () { openLyrics(song); });
    acts.appendChild(ly);

    var fav = el('button', 'icon-btn fav' + (song.favorite ? ' on' : ''), song.favorite ? '❤️' : '🤍');
    fav.type = 'button'; fav.title = 'Favorite'; fav.setAttribute('aria-label', 'Toggle favorite');
    fav.addEventListener('click', function () {
      api('/api/favorites/' + song.id, { method: 'POST', body: {} }).then(function (d) {
        song.favorite = d.favorite;
        fav.classList.toggle('on', d.favorite);
        fav.textContent = d.favorite ? '❤️' : '🤍';
        toast(d.favorite ? 'Added to favorites ❤️' : 'Removed from favorites');
        if (!d.favorite && opts.removeOnUnfav) row.remove();
      }).catch(function (e) { toast(e.message); });
    });
    acts.appendChild(fav);
    row.appendChild(acts);
    return row;
  }

  window.SongUI = {
    openLyrics: openLyrics,
    render: function (container, songs, opts) {
      opts = opts || {};
      container.textContent = '';
      if (!songs.length) { container.appendChild(el('p', 'muted', 'No songs found.')); return; }
      songs.forEach(function (s) { container.appendChild(buildRow(s, opts, songs)); });
      if (window.Player) Player.refresh();
    }
  };
})();
