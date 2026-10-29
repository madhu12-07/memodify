/* Mood quiz (Tamil + English). Scoring happens on the server. */
(function () {
  'use strict';
  var card = document.getElementById('question-card');
  var nextBtn = document.getElementById('next-btn');
  var backBtn = document.getElementById('back-btn');
  var bar = document.getElementById('progress');
  var counter = document.getElementById('counter');
  var msg = document.getElementById('quiz-msg');
  var questions = [];
  var answers = [];
  var i = 0;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function render() {
    var q = questions[i];
    card.textContent = '';
    card.classList.remove('fade-in'); void card.offsetWidth; card.classList.add('fade-in');
    card.appendChild(el('div', 'q-ta', q.ta));
    card.appendChild(el('div', 'q-en', q.en));
    var wrap = el('div', 'answers');
    q.options.forEach(function (o, idx) {
      var b = el('button', 'answer' + (answers[i] === idx ? ' selected' : ''));
      b.type = 'button';
      b.appendChild(el('b', '', o.ta));
      b.appendChild(el('span', '', o.en));
      b.addEventListener('click', function () {
        answers[i] = idx;
        wrap.querySelectorAll('.answer').forEach(function (x) { x.classList.remove('selected'); });
        b.classList.add('selected');
        nextBtn.disabled = false;
      });
      wrap.appendChild(b);
    });
    card.appendChild(wrap);
    counter.textContent = 'Question ' + (i + 1) + ' of ' + questions.length;
    bar.style.width = ((i + 1) / questions.length * 100) + '%';
    backBtn.disabled = i === 0;
    nextBtn.disabled = answers[i] === undefined;
    nextBtn.textContent = i === questions.length - 1 ? 'Finish ✓' : 'Next ›';
  }

  nextBtn.addEventListener('click', function () {
    if (i < questions.length - 1) { i++; render(); return; }
    nextBtn.disabled = true;
    msg.textContent = '';
    api('/api/recommend', { body: { source: 'quiz', answers: answers } })
      .then(function (d) { location.href = d.redirect; })
      .catch(function (e) { msg.textContent = e.message; nextBtn.disabled = false; });
  });
  backBtn.addEventListener('click', function () { if (i > 0) { i--; render(); } });

  api('/api/quiz').then(function (d) {
    questions = d.questions;
    render();
  }).catch(function (e) { card.textContent = e.message; });
})();
