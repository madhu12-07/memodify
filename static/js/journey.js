/* Mood Journey: starts at the chosen mood and, on its own, moves to the next mood after each time slice.
   Nothing is analysed while listening - the route is fixed up-front by the server. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var PATHS = window.JOURNEY_PATHS, INFO = window.MOOD_INFO, SLOT = window.SLOT_SECONDS, VAL = window.VALENCE;
  var startMood = $('setup').dataset.start;
  var minutes = 20;
  var S = null;           // running journey state
  var hovering = false;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function fmt(sec) { return MoodChart.fmt(sec); }

  // ------------------------------------------------------------------ setup screen
  function select(group, attr, value) {
    group.querySelectorAll('.pick').forEach(function (b) {
      var on = b.dataset[attr] === String(value);
      b.classList.toggle('selected', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
  }
  $('mood-chips').addEventListener('click', function (e) {
    var b = e.target.closest('.pick'); if (!b) return;
    startMood = b.dataset.mood; select($('mood-chips'), 'mood', startMood); renderRoute();
  });
  $('minute-chips').addEventListener('click', function (e) {
    var b = e.target.closest('.pick'); if (!b) return;
    minutes = parseInt(b.dataset.minutes, 10); select($('minute-chips'), 'minutes', minutes); renderRoute();
  });
  function renderRoute() {
    var route = $('route'); route.textContent = '';
    var path = PATHS[startMood];
    path.forEach(function (m, i) {
      if (i) route.appendChild(el('span', 'arrow', '→'));
      var c = el('span', 'stop', INFO[m].emoji + ' ' + INFO[m].label);
      c.style.setProperty('--c', INFO[m].color);
      route.appendChild(c);
    });
    route.appendChild(el('span', 'muted small', '  about ' + (minutes / path.length).toFixed(minutes / path.length % 1 ? 1 : 0) + ' min each'));
  }
  select($('mood-chips'), 'mood', startMood);
  select($('minute-chips'), 'minutes', minutes);
  renderRoute();

  var config = { youtube: false };
  api('/api/config').then(function (c) {
    config.youtube = !!c.youtube_enabled;
    if (!config.youtube) $('speed-wrap').classList.remove('hidden');   // demo speed only makes sense without real audio
  }).catch(function () {});

  $('begin-btn').addEventListener('click', function () {
    var btn = $('begin-btn'); btn.disabled = true; $('setup-msg').textContent = '';
    api('/api/journey', { body: { mood: startMood, minutes: minutes } }).then(function (J) {
      var speed = config.youtube ? 1 : parseInt($('speed').value, 10) || 1;
      begin(J, speed);
    }).catch(function (e) { $('setup-msg').textContent = e.message; btn.disabled = false; });
  });

  // ------------------------------------------------------------------ engine
  function stageIndex(t) {
    for (var i = 0; i < S.stages.length; i++) if (t < S.stages[i].end) return i;
    return S.stages.length - 1;
  }

  function begin(J, speed) {
    S = {
      stages: J.stages, total: J.total, speed: speed, youtube: J.youtube_enabled,
      elapsed: 0, paused: false, ended: false, ptr: J.stages.map(function () { return 0; }),
      played: [], cur: null, lastStage: -1, ytPlaying: false, player: null, last: performance.now(), tick: 0
    };
    $('setup').classList.add('hidden'); $('run').classList.remove('hidden');
    $('total').textContent = fmt(S.total);
    var tb = $('stage-table').querySelector('tbody'); tb.textContent = '';
    S.stages.forEach(function (s, i) {
      var tr = el('tr'); [i + 1, s.emoji + ' ' + s.label, fmt(s.start), fmt(s.end)].forEach(function (v) { tr.appendChild(el('td', '', String(v))); });
      tb.appendChild(tr);
    });
    var note = $('audio-note');
    if (!S.youtube) {
      note.textContent = 'Audio is off: add a YouTube API key in .env to hear songs inside this page (see README, "Play songs inside the website"). Until then every song is a ' +
        fmt(SLOT) + ' timed slot with its lyrics' + (speed > 1 ? ' (demo speed ' + speed + '×)' : '') + '.';
      note.classList.remove('hidden');
    }
    startSong();
    S.timer = setInterval(tick, 250);
  }

  function startSong() {
    if (S.ended) return;
    // follow the clock, but never skip a stage (a long song must not hide a whole mood)
    var idx = Math.min(stageIndex(S.elapsed), S.lastStage + 1), st = S.stages[idx];
    if (idx !== S.lastStage) {
      if (S.lastStage >= 0) {
        var prev = S.stages[S.lastStage];
        $('shift-note').textContent = 'Mood shift: ' + prev.label + ' → ' + st.label + ' ' + st.emoji;
        toast('Mood shift: ' + prev.label + ' → ' + st.label + ' ' + st.emoji);
      } else $('shift-note').textContent = 'Starting from ' + st.label.toLowerCase() + '. The mood will shift on its own.';
      S.lastStage = idx;
      $('stage-badge').textContent = 'Stage ' + (idx + 1) + ' of ' + S.stages.length;
      $('stage-title').textContent = st.emoji + ' ' + st.label;
      $('stage-badge').style.borderColor = st.color;
    }
    var song = st.songs[S.ptr[idx] % st.songs.length]; S.ptr[idx]++;
    S.cur = { song: song, stage: idx, songElapsed: 0, mode: 'slot', token: Math.random() };
    S.played.push({ t0: S.elapsed, t1: null, v: song.valence, title: song.title });
    $('song-title').textContent = song.title;
    $('song-meta').textContent = [song.movie, song.year, song.music_director].filter(Boolean).join(' · ');
    $('yt-link').href = song.search_url;
    $('yt-link').classList.toggle('hidden', !!S.youtube);      // only offered when a song cannot play inside the page
    $('yt-wrap').classList.add('hidden'); $('slot-wrap').classList.remove('hidden');
    S.ytPlaying = false;
    if (S.player) { try { S.player.stopVideo(); } catch (e) {} }     // never let the previous song keep playing
    loadLyrics(song);
    if (S.youtube) tryVideo(song, S.cur.token);
    renderUpNext(); drawChart(true);
  }

  function endSong() {
    if (S.played.length) S.played[S.played.length - 1].t1 = Math.min(S.elapsed, S.total);
    if (S.elapsed >= S.total - 0.5 && S.cur.stage === S.stages.length - 1) finish(); else startSong();
  }

  function tick() {
    if (!S || S.ended) return;
    var now = performance.now(), dt = Math.min((now - S.last) / 1000, 2); S.last = now;
    if (!S.paused) {
      var advancing = S.cur.mode === 'slot' || S.ytPlaying;
      if (advancing) { var d = dt * S.speed; S.elapsed += d; S.cur.songElapsed += d; }
      if (S.cur.mode === 'slot') {
        var lastStage = S.cur.stage === S.stages.length - 1;
        if (S.cur.songElapsed >= SLOT || (S.elapsed >= S.total && lastStage)) { endSong(); if (S.ended) return; }
      } else if (S.elapsed >= S.total + 600) { finish(); return; }
    }
    S.tick++;
    updateUI();
  }

  function updateUI() {
    $('elapsed').textContent = fmt(S.elapsed);
    $('journey-progress').style.width = Math.min(100, S.elapsed / S.total * 100) + '%';
    if (S.cur.mode === 'slot') $('slot-progress').style.width = Math.min(100, S.cur.songElapsed / SLOT * 100) + '%';
    var cs = S.cur.stage, last = S.stages.length - 1, st = S.stages[cs], nxt = S.stages[cs + 1];
    var clockIdx = Math.min(stageIndex(S.elapsed), last);
    if (cs < last) {
      if (clockIdx > cs) $('shift-note').textContent = 'Mood shifts to ' + nxt.label.toLowerCase() + ' ' + nxt.emoji + ' right after this song';
      else $('shift-note').textContent = 'Next: ' + nxt.label + ' ' + nxt.emoji + ' in ' + fmt(st.end - S.elapsed);
    } else if (S.elapsed >= S.total) $('shift-note').textContent = 'Finishing this song…';
    else $('shift-note').textContent = 'Final stage: ' + st.label.toLowerCase() + '. Enjoy!';
    if (S.tick % 4 === 0 && !hovering) drawChart(false);
  }

  function chartOpts(interactive) {
    return { stages: S.stages, total: S.total, valence: VAL, played: S.played, now: S.elapsed, interactive: interactive };
  }
  function drawChart() { MoodChart.render($('chart'), chartOpts(true)); }
  $('chart').addEventListener('mouseenter', function () { hovering = true; });
  $('chart').addEventListener('mouseleave', function () { hovering = false; });

  function renderUpNext() {
    var box = $('upnext'); box.textContent = '';
    var shown = 0;
    for (var i = S.cur.stage; i < S.stages.length && shown < 4; i++) {
      var st = S.stages[i], from = i === S.cur.stage ? S.ptr[i] : 0;
      for (var j = from; j < st.songs.length && shown < 4; j++, shown++) {
        var row = el('div', 'up');
        var dot = el('i'); dot.style.background = st.color; row.appendChild(dot);
        var t = el('div'); t.appendChild(el('b', '', st.songs[j].title));
        t.appendChild(el('span', 'muted small', ' ' + st.label + (st.songs[j].movie ? ' · ' + st.songs[j].movie : '')));
        row.appendChild(t); box.appendChild(row);
      }
    }
    if (!shown) box.appendChild(el('p', 'muted small', 'That was the last song of the journey.'));
  }

  // ------------------------------------------------------------------ lyrics
  var lyrics = { tamil: '', english: '', lang: 'tamil' };
  function showLyrics() {
    var txt = lyrics[lyrics.lang] || lyrics.tamil || lyrics.english || 'Lyrics not available for this song.';
    $('lyrics-text').textContent = txt; $('lyrics-text').scrollTop = 0;
    document.querySelectorAll('.seg-btn').forEach(function (b) { b.classList.toggle('selected', b.dataset.lang === lyrics.lang); });
  }
  document.querySelector('.seg').addEventListener('click', function (e) {
    var b = e.target.closest('.seg-btn'); if (!b) return; lyrics.lang = b.dataset.lang; showLyrics();
  });
  function loadLyrics(song) {
    $('lyrics-text').textContent = 'Loading…';
    api('/api/lyrics/' + song.id).then(function (d) {
      if (!S || !S.cur || S.cur.song.id !== song.id) return;
      lyrics.tamil = d.tamil; lyrics.english = d.english; showLyrics();
    }).catch(function () { $('lyrics-text').textContent = 'Could not load lyrics.'; });
  }

  // ------------------------------------------------------------------ optional YouTube playback (in this page)
  var ytScript = null;
  function ensureYT(cb) {
    if (window.YT && YT.Player) return cb();
    if (!ytScript) {
      ytScript = document.createElement('script'); ytScript.src = 'https://www.youtube.com/iframe_api';
      var prior = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = function () { if (prior) prior(); (ensureYT.q || []).forEach(function (f) { f(); }); };
      document.head.appendChild(ytScript);
    }
    (ensureYT.q = ensureYT.q || []).push(cb);
  }
  function fallbackToSlot(token, msg) {
    if (!S || !S.cur || S.cur.token !== token) return;
    S.cur.mode = 'slot'; S.ytPlaying = false;
    $('yt-link').classList.remove('hidden');
    $('yt-wrap').classList.add('hidden'); $('slot-wrap').classList.remove('hidden');
    if (msg) { $('audio-note').textContent = msg; $('audio-note').classList.remove('hidden'); }
  }
  var REASONS = {
    no_key: 'Songs cannot play inside the page yet (no YouTube API key), so this one runs as a timed slot with lyrics.',
    quota: 'The daily YouTube search limit is used up, so this song runs as a timed slot with lyrics.',
    key: 'The YouTube API key was rejected, so this song runs as a timed slot with lyrics.',
    error: 'Could not reach YouTube, so this song runs as a timed slot with lyrics.'
  };
  function tryVideo(song, token) {
    api('/api/play/' + song.id).then(function (d) {
      if (!S || !S.cur || S.cur.token !== token) return;
      var cands = d.candidates && d.candidates.length ? d.candidates : (d.video_id ? [d.video_id] : []);
      if (!cands.length) return fallbackToSlot(token, REASONS[d.reason] || 'No playable video found for this song, so it runs as a timed slot with lyrics.');
      S.cur.cands = cands; S.cur.ci = 0;
      ensureYT(function () {
        if (!S || !S.cur || S.cur.token !== token) return;
        S.cur.mode = 'yt';
        $('slot-wrap').classList.add('hidden'); $('yt-wrap').classList.remove('hidden');
        $('audio-note').classList.add('hidden');
        if (S.player) { S.player.loadVideoById(cands[0]); return; }
        var vars = { autoplay: 1, controls: 1, rel: 0, modestbranding: 1, fs: 0, playsinline: 1 };
        if (/^https?:$/.test(location.protocol)) vars.origin = location.origin;
        S.player = new YT.Player('yt', {
          width: '100%', height: '260', videoId: cands[0], playerVars: vars,
          events: {
            onReady: function (e) { e.target.playVideo(); },
            onStateChange: function (e) {
              if (!S || S.ended || !S.cur || S.cur.mode !== 'yt') return;
              S.ytPlaying = e.data === 1;
              if (e.data === 0) endSong();
            },
            onError: function (e) {
              if (!S || !S.cur) return;
              var c = S.cur, code = e && e.data ? ' (YouTube error ' + e.data + ')' : '';
              if (c.cands && c.ci + 1 < c.cands.length) { c.ci++; S.player.loadVideoById(c.cands[c.ci]); return; }   // next candidate
              var tried = (c.cands || []).slice(), tok = c.token;
              if (!c.retried) {                                // every saved video failed: forget them, search again once
                c.retried = true;
                api('/api/play/' + c.song.id + '/broken', { body: { ids: tried } })
                  .then(function () { return api('/api/play/' + c.song.id); })
                  .then(function (d) {
                    if (!S || !S.cur || S.cur.token !== tok) return;
                    var fresh = (d.candidates || []).filter(function (v) { return tried.indexOf(v) < 0; });
                    if (fresh.length) { c.cands = fresh; c.ci = 0; S.player.loadVideoById(fresh[0]); }
                    else fallbackToSlot(tok, 'No video of this song can play inside the page' + code + ', so it runs as a timed slot with lyrics. Tap Next song for another.');
                  })
                  .catch(function () { fallbackToSlot(tok, 'This video cannot be embedded' + code + ', so it runs as a timed slot with lyrics.'); });
                return;
              }
              fallbackToSlot(tok, 'No video of this song can play inside the page' + code + ', so it runs as a timed slot with lyrics. Tap Next song for another.');
            }
          }
        });
      });
    }).catch(function () { fallbackToSlot(token, REASONS.error); });
  }

  // ------------------------------------------------------------------ controls
  $('pause-btn').addEventListener('click', function () {
    if (!S || S.ended) return;
    S.paused = !S.paused;
    $('pause-btn').textContent = S.paused ? '▶ Resume' : '⏸ Pause';
    if (S.player && S.cur.mode === 'yt') { try { S.paused ? S.player.pauseVideo() : S.player.playVideo(); } catch (e) {} }
  });
  $('skip-btn').addEventListener('click', function () {
    if (!S || S.ended) return;
    if (S.elapsed >= S.total) return finish();
    if (S.played.length) S.played[S.played.length - 1].t1 = S.elapsed;
    startSong();
  });
  $('stop-btn').addEventListener('click', function () { if (S && !S.ended) finish(true); });
  $('again-btn').addEventListener('click', function () { location.href = '/journey'; });

  function finish(early) {
    if (!S || S.ended) return;
    S.ended = true; clearInterval(S.timer);
    if (S.player) { try { S.player.destroy(); } catch (e) {} S.player = null; }
    if (S.played.length && S.played[S.played.length - 1].t1 == null) S.played[S.played.length - 1].t1 = Math.min(S.elapsed, S.total);
    var first = S.stages[0], last = S.stages[S.stages.length - 1];
    $('run').classList.add('hidden'); $('done').classList.remove('hidden');
    $('done-text').textContent = (early ? 'You ended the journey early after ' : 'You travelled from ' + first.label.toLowerCase() + ' to ' + last.label.toLowerCase() + ' in ') +
      fmt(Math.min(S.elapsed, S.total)) + ' · ' + S.played.length + ' song' + (S.played.length === 1 ? '' : 's') + '.';
    MoodChart.render($('done-chart'), { stages: S.stages, total: S.total, valence: VAL, played: S.played, now: null, interactive: true });
  }

  window.addEventListener('pagehide', function () { if (S && S.timer) clearInterval(S.timer); });
  window.__journey = { state: function () { return S; } };      // handy for debugging in the browser console
})();
