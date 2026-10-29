/* Mood curve: plain SVG, no library.
   - coloured bands = journey stages (each labelled, so colour is never the only cue)
   - dashed line    = the planned route (valence of each stage's mood, eased between stages)
   - solid line     = what has actually played (one level per song) + a dot for "now"
   - hover shows a crosshair and a small tooltip */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var W = 640, H = 290, M = { l: 54, r: 14, t: 34, b: 36 };
  var YTICKS = [{ v: 0.1, t: 'Sad' }, { v: 0.55, t: 'Calm' }, { v: 0.9, t: 'Happy' }];

  function svg(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function fmt(sec) {
    sec = Math.max(0, Math.round(sec));
    var m = Math.floor(sec / 60), s = sec % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  // planned valence at time t: ease between the middle of one stage and the middle of the next
  function planned(stages, valence, t) {
    var pts = stages.map(function (s) { return { t: (s.start + s.end) / 2, v: valence[s.mood] }; });
    pts.unshift({ t: 0, v: pts[0].v });
    pts.push({ t: stages[stages.length - 1].end, v: pts[pts.length - 1].v });
    for (var i = 0; i < pts.length - 1; i++) {
      if (t <= pts[i + 1].t) {
        var span = pts[i + 1].t - pts[i].t || 1;
        var f = (1 - Math.cos(Math.PI * Math.min(1, Math.max(0, (t - pts[i].t) / span)))) / 2;
        return pts[i].v + (pts[i + 1].v - pts[i].v) * f;
      }
    }
    return pts[pts.length - 1].v;
  }

  function render(container, o) {
    var stages = o.stages, total = o.total, valence = o.valence, played = o.played || [], now = o.now;
    container.textContent = '';
    container.style.position = 'relative';
    var root = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, width: '100%', preserveAspectRatio: 'xMidYMid meet', 'class': 'mc' }, container);
    var pw = W - M.l - M.r, ph = H - M.t - M.b;
    var x = function (t) { return M.l + (t / total) * pw; };
    var y = function (v) { return M.t + (1 - v) * ph; };

    // stage bands + labels
    stages.forEach(function (s, i) {
      svg('rect', { x: x(s.start), y: M.t, width: x(s.end) - x(s.start), height: ph, fill: s.color, 'fill-opacity': 0.13 }, root);
      if (i > 0) svg('line', { x1: x(s.start), x2: x(s.start), y1: M.t, y2: M.t + ph, stroke: 'var(--surface)', 'stroke-width': 2 }, root);
      var lab = svg('text', { x: (x(s.start) + x(s.end)) / 2, y: M.t - 10, 'text-anchor': 'middle', 'class': 'mc-stage' }, root);
      lab.textContent = s.emoji + ' ' + s.label;
    });

    // recessive grid + y labels
    YTICKS.forEach(function (tk) {
      svg('line', { x1: M.l, x2: W - M.r, y1: y(tk.v), y2: y(tk.v), 'class': 'mc-grid' }, root);
      var t = svg('text', { x: M.l - 8, y: y(tk.v) + 4, 'text-anchor': 'end', 'class': 'mc-axis' }, root);
      t.textContent = tk.t;
    });
    // x labels at stage borders
    var xs = stages.map(function (s) { return s.start; }).concat([total]);
    xs.forEach(function (t, i) {
      var a = svg('text', { x: x(t), y: H - 12, 'text-anchor': i === 0 ? 'start' : (i === xs.length - 1 ? 'end' : 'middle'), 'class': 'mc-axis' }, root);
      a.textContent = fmt(t);
    });
    svg('line', { x1: M.l, x2: W - M.r, y1: M.t + ph, y2: M.t + ph, 'class': 'mc-base' }, root);

    // planned route (dashed)
    var d = '';
    for (var i = 0; i <= 80; i++) {
      var t = (i / 80) * total;
      d += (i ? 'L' : 'M') + x(t).toFixed(1) + ' ' + y(planned(stages, valence, t)).toFixed(1);
    }
    svg('path', { d: d, 'class': 'mc-plan' }, root);

    // what actually played: one level per song
    if (played.length) {
      var p = '';
      played.forEach(function (s, i) {
        var t1 = Math.min(s.t1 == null ? now : s.t1, total);
        p += (i ? 'L' : 'M') + x(s.t0).toFixed(1) + ' ' + y(s.v).toFixed(1) + 'L' + x(t1).toFixed(1) + ' ' + y(s.v).toFixed(1);
      });
      svg('path', { d: p, 'class': 'mc-played' }, root);
      var last = played[played.length - 1];
      if (now != null && now < total + 1) {
        svg('circle', { cx: x(Math.min(now, total)), cy: y(last.v), r: 6, 'class': 'mc-dot' }, root);
      }
    }

    // hover layer
    if (o.interactive === false) return;
    var cross = svg('line', { y1: M.t, y2: M.t + ph, 'class': 'mc-cross', visibility: 'hidden' }, root);
    var tip = document.createElement('div');
    tip.className = 'mc-tip'; tip.style.display = 'none';
    container.appendChild(tip);
    var hit = svg('rect', { x: M.l, y: M.t, width: pw, height: ph, fill: 'transparent' }, root);
    function move(ev) {
      var r = root.getBoundingClientRect();
      var px = ((ev.clientX - r.left) / r.width) * W;
      var t = Math.min(total, Math.max(0, ((px - M.l) / pw) * total));
      var st = stages.filter(function (s) { return t >= s.start && t < s.end; })[0] || stages[stages.length - 1];
      var song = played.filter(function (s) { return t >= s.t0 && t <= (s.t1 == null ? now : s.t1); })[0];
      cross.setAttribute('x1', x(t)); cross.setAttribute('x2', x(t)); cross.setAttribute('visibility', 'visible');
      tip.textContent = '';
      var b = document.createElement('b'); b.textContent = fmt(t) + ' · ' + st.label + ' stage'; tip.appendChild(b);
      var l1 = document.createElement('div'); l1.textContent = 'Planned: ' + Math.round(planned(stages, valence, t) * 100) + '% positive'; tip.appendChild(l1);
      if (song) { var l2 = document.createElement('div'); l2.textContent = '♪ ' + song.title + ' (' + Math.round(song.v * 100) + '%)'; tip.appendChild(l2); }
      tip.style.display = 'block';
      var left = (ev.clientX - r.left) + 12;
      if (left > r.width - 190) left = (ev.clientX - r.left) - 190;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = (ev.clientY - r.top - 10) + 'px';
    }
    hit.addEventListener('mousemove', move);
    hit.addEventListener('mouseleave', function () { cross.setAttribute('visibility', 'hidden'); tip.style.display = 'none'; });
  }

  window.MoodChart = { render: render, planned: planned, fmt: fmt };
})();
