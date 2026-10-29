/* In-page music player (Results + Favorites).
   Songs play right here inside the website using YouTube's embedded player - the visitor never leaves the page.
   Flow: Play -> /api/play/<id> gives video ids -> the first one plays; if a video refuses to embed the next
   id is tried; when a song ends the next song in the list starts by itself. */
(function () {
  'use strict';

  var MESSAGES = {
    no_key: 'Songs cannot play inside the page yet: the site owner needs to add a YouTube API key (see README, "Play songs inside the website").',
    quota: 'YouTube allows only a limited number of new song look-ups per day and that limit is used up. Songs that were played or indexed before still work; new ones work again tomorrow (see README: build_video_index).',
    key: 'The YouTube API key was rejected. Please check YOUTUBE_API_KEY in the .env file.',
    error: 'Could not reach YouTube just now. Please check the internet connection and try again.',
    not_found: 'No playable video was found for this song.'
  };

  var S = {
    list: [], index: -1, cands: [], ci: 0, token: 0, failStreak: 0,
    yt: null, ytReady: false, pendingId: null, ui: null, wantPlay: true
  };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  // ------------------------------------------------------------------ panel
  function buildPanel() {
    if (S.ui) return S.ui;
    var slot = document.getElementById('player-slot');
    if (!slot) return null;
    var box = el('section', 'card player hidden');
    box.setAttribute('aria-label', 'Music player');
    var grid = el('div', 'player-grid');

    var frame = el('div', 'player-frame');           // YouTube's player must stay visible (its rule), so it gets a tidy frame
    var target = el('div'); target.id = 'player-yt';
    frame.appendChild(target);
    grid.appendChild(frame);

    var info = el('div', 'player-info');
    var eyebrow = el('p', 'eyebrow');
    var wave = el('span', 'wave'); wave.setAttribute('aria-hidden', 'true');
    for (var k = 0; k < 4; k++) wave.appendChild(el('i'));
    eyebrow.appendChild(wave); eyebrow.appendChild(document.createTextNode(' NOW PLAYING'));
    var title = el('h2', 'player-title', '-');
    var meta = el('p', 'muted player-meta', '');
    info.appendChild(eyebrow); info.appendChild(title); info.appendChild(meta);

    var msg = el('p', 'small muted player-msg', '');
    msg.setAttribute('role', 'status'); msg.setAttribute('aria-live', 'polite');
    var fallback = el('a', 'small hidden', 'Open this song on YouTube instead ↗');
    fallback.target = '_blank'; fallback.rel = 'noopener';
    info.appendChild(msg); info.appendChild(fallback);

    var row = el('div', 'row player-controls');
    var prev = el('button', 'btn ghost small', '⏮ Previous'); prev.type = 'button';
    var toggle = el('button', 'btn small', '⏸ Pause'); toggle.type = 'button';
    var next = el('button', 'btn ghost small', 'Next ⏭'); next.type = 'button';
    row.appendChild(prev); row.appendChild(toggle); row.appendChild(next);
    info.appendChild(row);
    grid.appendChild(info);
    box.appendChild(grid);

    prev.addEventListener('click', function () { go(S.index - 1, false); });
    next.addEventListener('click', function () { go(S.index + 1, false); });
    toggle.addEventListener('click', function () {
      if (!S.yt || !S.ytReady) return;
      try {
        var st = S.yt.getPlayerState();
        if (st === 1) S.yt.pauseVideo(); else S.yt.playVideo();
      } catch (e) {}
    });

    slot.appendChild(box);
    S.ui = { box: box, wave: wave, title: title, meta: meta, msg: msg, fallback: fallback, toggle: toggle, prev: prev, next: next };
    return S.ui;
  }

  function setMsg(text, showFallbackFor) {
    var ui = S.ui; if (!ui) return;
    ui.msg.textContent = text || '';
    if (showFallbackFor) { ui.fallback.href = showFallbackFor; ui.fallback.classList.remove('hidden'); }
    else ui.fallback.classList.add('hidden');
  }

  function highlight() {
    var cur = S.list[S.index];
    document.querySelectorAll('.song').forEach(function (row) {
      var on = !!cur && String(cur.id) === row.dataset.id;
      row.classList.toggle('playing', on);
      var b = row.querySelector('.icon-btn.play');
      if (b) { b.textContent = on ? '⏸' : '▶'; b.setAttribute('aria-label', (on ? 'Pause ' : 'Play ') + row.querySelector('h3').textContent); }
    });
    if (S.ui) {
      S.ui.prev.disabled = S.index <= 0;
      S.ui.next.disabled = S.index < 0 || S.index >= S.list.length - 1;
    }
  }

  // ------------------------------------------------------------------ YouTube iframe API
  var apiRequested = false, apiWaiters = [];
  function withYT(cb) {
    if (window.YT && YT.Player) return cb();
    apiWaiters.push(cb);
    if (apiRequested) return;
    apiRequested = true;
    var prior = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = function () {
      if (prior) prior();
      var w = apiWaiters; apiWaiters = []; w.forEach(function (f) { f(); });
    };
    var s = document.createElement('script');
    s.src = 'https://www.youtube.com/iframe_api';
    s.onerror = function () { setMsg(MESSAGES.error); };
    document.head.appendChild(s);
  }

  function loadVideo(videoId) {
    withYT(function () {
      if (S.yt) {
        if (S.ytReady) S.yt.loadVideoById(videoId); else S.pendingId = videoId;
        return;
      }
      S.pendingId = videoId;
      var vars = { autoplay: 1, rel: 0, playsinline: 1, modestbranding: 1 };
      if (/^https?:$/.test(location.protocol)) vars.origin = location.origin;
      S.yt = new YT.Player('player-yt', {
        width: '100%', height: '100%', videoId: videoId, playerVars: vars,
        events: {
          onReady: function () {
            S.ytReady = true;
            if (S.pendingId) { S.yt.loadVideoById(S.pendingId); S.pendingId = null; }
          },
          onStateChange: onState,
          onError: onVideoError
        }
      });
    });
  }

  function rowIcon(playing) {
    var b = document.querySelector('.song.playing .icon-btn.play');
    if (b) b.textContent = playing ? '⏸' : '▶';
  }

  function onState(e) {
    if (!S.ui) return;
    if (e.data === 1) rowIcon(true); else if (e.data === 2) rowIcon(false);
    S.ui.wave.classList.toggle('on', e.data === 1);
    if (e.data === 1) { S.failStreak = 0; setMsg(''); S.ui.toggle.textContent = '⏸ Pause'; }
    else if (e.data === 2) S.ui.toggle.textContent = '▶ Play';
    else if (e.data === 0) go(S.index + 1, true);          // song finished -> next song
  }

  function onVideoError(e) {
    S.lastErr = e && e.data ? ' (YouTube error ' + e.data + ')' : '';
    // this video cannot be played here (not embeddable, removed, private, blocked...): try the next candidate
    if (S.ci + 1 < S.cands.length) {
      S.ci++;
      loadVideo(S.cands[S.ci]);
      return;
    }
    var song = S.list[S.index], tok = S.token, tried = S.cands.slice();
    if (!S.retried && song) {
      // every saved video failed: forget them and ask for fresh ones, once
      S.retried = true;
      setMsg('That video cannot be played here. Looking for another version…');
      api('/api/play/' + song.id + '/broken', { body: { ids: tried } })
        .then(function () { return api('/api/play/' + song.id + '?more=1&exclude=' + encodeURIComponent(tried.join(','))); })
        .then(function (d) {
          if (tok !== S.token) return;
          var fresh = (d.candidates || []).filter(function (v) { return tried.indexOf(v) < 0; });
          if (fresh.length) { S.cands = fresh; S.ci = 0; setMsg(''); loadVideo(fresh[0]); }
          else giveUp('This song cannot be played inside the page' + S.lastErr + '.', true);
        })
        .catch(function () { if (tok === S.token) giveUp('This song cannot be played inside the page' + S.lastErr + '.', true); });
      return;
    }
    giveUp('This song cannot be played inside the page' + S.lastErr + '.', true);
  }

  function giveUp(text, autoSkip) {
    var song = S.list[S.index];
    setMsg(text + (autoSkip ? ' Skipping to the next song…' : ''), song ? song.search_url : null);
    S.failStreak++;
    if (autoSkip && S.failStreak < S.list.length && S.index < S.list.length - 1) {
      var tok = S.token;
      setTimeout(function () { if (tok === S.token) go(S.index + 1, true); }, 1800);
    }
  }

  // daily YouTube search limit used up: do not stop - jump to the next song that is already known (needs no search)
  function skipToReady(i, tok) {
    var order = [];
    for (var k = 1; k < S.list.length; k++) order.push((i + k) % S.list.length);
    var ids = order.map(function (j) { return S.list[j].id; });
    setMsg('Looking for the next song that is ready to play…');
    api('/api/playable?ids=' + ids.join(',')).then(function (r) {
      if (tok !== S.token) return;
      var ready = (r.playable || []);
      var pick = order.filter(function (j) { return ready.indexOf(S.list[j].id) >= 0; })[0];
      if (pick === undefined) return giveUp(MESSAGES.quota, false);
      setMsg('The daily YouTube search limit is used up, so the next ready song is starting…');
      setTimeout(function () { if (tok === S.token) go(pick, true); }, 900);
    }).catch(function () { if (tok === S.token) giveUp(MESSAGES.quota, false); });
  }

  // ------------------------------------------------------------------ play a song
  function go(i, auto) {
    if (i < 0 || i >= S.list.length) {
      if (auto && S.ui) setMsg('That was the last song in the list. Tap Shuffle (or pick a song) to keep listening.');
      return;
    }
    var ui = buildPanel(); if (!ui) return;
    S.index = i; S.auto = !!auto; S.cands = []; S.ci = 0; S.retried = false; S.lastErr = '';
    var tok = ++S.token, song = S.list[i];
    try { if (S.yt && S.ytReady) S.yt.stopVideo(); } catch (e) {}
    ui.box.classList.remove('hidden');
    ui.title.textContent = song.title;
    ui.meta.textContent = [song.movie, song.year, song.music_director].filter(Boolean).join(' · ');
    setMsg('Finding the song…');
    highlight();
    if (!auto) ui.box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    api('/api/play/' + song.id).then(function (d) {
      if (tok !== S.token) return;
      if ((!d.candidates || !d.candidates.length) && d.reason === 'quota') return skipToReady(i, tok);
      if (!d.candidates || !d.candidates.length) {
        // no key at all -> nothing can play, so do not skip through the whole list;
        // otherwise just this song is unavailable and autoplay moves on to the next one
        var global = (d.reason === 'no_key' && !d.enabled) || d.reason === 'quota' || d.reason === 'key';
        var text = d.reason === 'no_key' && d.enabled ? MESSAGES.not_found : (MESSAGES[d.reason] || MESSAGES.not_found);
        return giveUp(text, !global);      // this song has no match: move on to the next song by itself
      }
      S.cands = d.candidates; S.ci = 0;
      setMsg('');
      loadVideo(S.cands[0]);
    }).catch(function (e) {
      if (tok === S.token) setMsg(e.message || MESSAGES.error);
    });
  }

  window.Player = {
    /** Play `song` and use `list` (the songs shown on the page) for Next / Previous / auto-play. */
    play: function (song, list) {
      var cur = S.list[S.index];
      if (cur && cur.id === song.id && S.yt && S.ytReady) {   // same song: act as pause / resume
        try { S.yt.getPlayerState() === 1 ? S.yt.pauseVideo() : S.yt.playVideo(); } catch (e) {}
        return;
      }
      S.list = list && list.length ? list : [song];
      S.failStreak = 0;
      var i = S.list.findIndex(function (s) { return s.id === song.id; });
      go(i < 0 ? 0 : i, false);
    },
    /** Called after the page re-draws its song rows (e.g. Shuffle) so the playing song stays highlighted. */
    refresh: highlight,
    _state: S          // for tests / debugging in the browser console
  };
})();
