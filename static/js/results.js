/* Results page: load songs for the mood; "Shuffle" brings songs not shown yet */
(function () {
  'use strict';
  var list = document.getElementById('song-list');
  var mood = list.dataset.mood, age = list.dataset.age || '';
  var shown = [];
  var moreBtn = document.getElementById('more-btn');

  function load() {
    var url = '/api/songs?mood=' + encodeURIComponent(mood) + '&age=' + encodeURIComponent(age) + '&exclude=' + shown.join(',');
    moreBtn.disabled = true;
    api(url).then(function (d) {
      shown = shown.concat(d.songs.map(function (s) { return s.id; }));
      if (shown.length > 200) shown = shown.slice(-100);   // keep the URL short
      SongUI.render(list, d.songs);
    }).catch(function (e) {
      list.textContent = e.message;
    }).then(function () { moreBtn.disabled = false; });
  }

  moreBtn.addEventListener('click', load);
  load();
})();
