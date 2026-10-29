/* Face mood detection with face-api.js (runs fully in the browser) */
(function () {
  'use strict';

  var MODEL_URL = '/static/vendor/face-api/model';
  var LABELS = {
    neutral: 'Neutral', happy: 'Happy', sad: 'Sad', angry: 'Angry',
    fearful: 'Fearful', disgusted: 'Disgusted', surprised: 'Surprised'
  };
  var EMO = {
    neutral: '\ud83d\ude10', happy: '\ud83d\ude04', sad: '\ud83d\ude22', angry: '\ud83d\ude20',
    fearful: '\ud83d\ude28', disgusted: '\ud83e\udd22', surprised: '\ud83d\ude32'
  };
  var KEYS = Object.keys(LABELS);
  var liveEmoji = document.getElementById('live-emoji');
  var liveLabel = document.getElementById('live-label');
  var liveKey = null;

  var video = document.getElementById('video');
  var overlay = document.getElementById('overlay');
  var box = document.getElementById('camera-box');
  var placeholder = document.getElementById('placeholder');
  var statusEl = document.getElementById('status');
  var startBtn = document.getElementById('start-btn');
  var detectBtn = document.getElementById('detect-btn');
  var stopBtn = document.getElementById('stop-btn');
  var barsEl = document.getElementById('bars');

  var stream = null, timer = null, busy = false, modelsReady = false;
  var sampling = null; // array while collecting samples

  function say(text, cls) {
    statusEl.className = 'status' + (cls ? ' ' + cls : '');
    statusEl.textContent = text;
  }

  // ---- bars ----
  var barFill = {};
  KEYS.forEach(function (k) {
    var row = document.createElement('div'); row.className = 'bar-row';
    var name = document.createElement('span'); name.textContent = EMO[k] + ' ' + LABELS[k];
    var bar = document.createElement('div'); bar.className = 'bar';
    var fill = document.createElement('span'); bar.appendChild(fill);
    var pct = document.createElement('span'); pct.textContent = '0%';
    row.appendChild(name); row.appendChild(bar); row.appendChild(pct);
    barsEl.appendChild(row);
    barFill[k] = { fill: fill, pct: pct };
  });
  function showLive(key) {
    if (key === liveKey) return;
    liveKey = key;
    liveEmoji.textContent = key ? EMO[key] : '\u2753';
    liveLabel.textContent = key ? LABELS[key] : 'No face yet';
    liveEmoji.className = 'live-emoji' + (key ? ' pop' : '');
  }
  function topKey(expr) {
    var best = null, bv = 0;
    KEYS.forEach(function (k) { if ((expr[k] || 0) > bv) { bv = expr[k]; best = k; } });
    return best;
  }
  function updateBars(expr) {
    showLive(expr ? topKey(expr) : null);
    KEYS.forEach(function (k) {
      var v = expr ? (expr[k] || 0) : 0;
      barFill[k].fill.style.width = Math.round(v * 100) + '%';
      barFill[k].pct.textContent = Math.round(v * 100) + '%';
    });
  }

  // ---- models ----
  if (typeof faceapi === 'undefined') {
    say('The face library did not load. Please refresh the page.', 'error');
    return;
  }
  Promise.all([
    faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
    faceapi.nets.faceExpressionNet.loadFromUri(MODEL_URL)
  ]).then(function () {
    modelsReady = true;
    startBtn.disabled = false;
    say('Ready! Press "Start camera".', 'ok');
  }).catch(function () {
    say('Could not load the face models. Is the server running?', 'error');
  });

  // ---- camera ----
  function insecure() {
    var h = location.hostname;
    return !window.isSecureContext && h !== 'localhost' && h !== '127.0.0.1';
  }

  startBtn.addEventListener('click', function () {
    if (insecure() || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      say('The camera needs https or localhost. Open the app at http://localhost:5000.', 'error');
      return;
    }
    startBtn.disabled = true;
    say('Waiting for camera permission… please click Allow.');
    navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false })
      .then(function (s) {
        stream = s;
        video.srcObject = s;
        return video.play();
      })
      .then(function () {
        placeholder.classList.add('hidden');
        detectBtn.disabled = false;
        stopBtn.disabled = false;
        say('Face the camera, then press "Detect my mood".');
        timer = setInterval(loop, 250);
      })
      .catch(function (err) {
        startBtn.disabled = false;
        var m = 'Could not open the camera.';
        if (err && err.name === 'NotAllowedError') m = 'Camera permission was denied. Allow it in your browser settings.';
        else if (err && err.name === 'NotFoundError') m = 'No camera was found.';
        else if (err && err.name === 'NotReadableError') m = 'Another app is using the camera. Close it and try again.';
        say(m + ' You can use the Quiz or Emoji instead.', 'error');
      });
  });

  function stopCamera() {
    clearInterval(timer); timer = null; sampling = null;
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null; video.srcObject = null;
    placeholder.classList.remove('hidden');
    box.classList.remove('scanning');
    var ctx = overlay.getContext('2d'); ctx.clearRect(0, 0, overlay.width, overlay.height);
    updateBars(null);
    detectBtn.disabled = true; stopBtn.disabled = true; startBtn.disabled = !modelsReady;
  }
  stopBtn.addEventListener('click', function () { stopCamera(); say('Camera stopped.'); });

  // ---- detection loop ----
  var opts = new faceapi.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.5 });
  function loop() {
    if (busy || !stream || video.readyState < 2) return;
    busy = true;
    faceapi.detectSingleFace(video, opts).withFaceExpressions().then(function (res) {
      var ctx = overlay.getContext('2d');
      overlay.width = video.videoWidth; overlay.height = video.videoHeight;
      ctx.clearRect(0, 0, overlay.width, overlay.height);
      if (!res) { updateBars(null); return; }
      var b = res.detection.box;
      ctx.strokeStyle = '#e8d3a8'; ctx.lineWidth = 3;
      ctx.strokeRect(b.x, b.y, b.width, b.height);
      updateBars(res.expressions);
      if (sampling) sampling.push(res.expressions);
    }).catch(function () { /* ignore a bad frame */ }).then(function () { busy = false; });
  }

  // ---- detect my mood: average ~3 seconds of frames ----
  detectBtn.addEventListener('click', function () {
    if (!stream) return;
    detectBtn.disabled = true;
    sampling = [];
    box.classList.add('scanning');
    say('Scanning… hold still for 3 seconds 😊');
    setTimeout(finish, 3200);
  });

  function finish() {
    var samples = sampling || [];
    sampling = null;
    box.classList.remove('scanning');
    if (samples.length < 3) {
      say('Could not see your face clearly. Add some light, look at the camera and try again.', 'error');
      detectBtn.disabled = false;
      return;
    }
    var avg = {};
    KEYS.forEach(function (k) {
      avg[k] = samples.reduce(function (a, s) { return a + (s[k] || 0); }, 0) / samples.length;
    });
    say('Mood found! Getting your songs… 🎶', 'ok');
    api('/api/recommend', { body: { source: 'face', expressions: avg } })
      .then(function (d) { stopCamera(); location.href = d.redirect; })
      .catch(function (e) { say(e.message, 'error'); detectBtn.disabled = false; });
  }

  window.addEventListener('pagehide', stopCamera);
})();
