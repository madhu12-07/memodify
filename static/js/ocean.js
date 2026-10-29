/* rising bubbles for the ocean background (skipped when the visitor prefers reduced motion) */
(function () {
  var box = document.getElementById('bubbles');
  if (!box || (window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches)) return;
  var count = window.innerWidth < 700 ? 9 : 18;
  for (var i = 0; i < count; i++) {
    var b = document.createElement('i'), s = 6 + Math.random() * 30;
    b.style.cssText = 'width:' + s + 'px;height:' + s + 'px;left:' + (Math.random() * 100) + '%;' +
      'animation-duration:' + (14 + Math.random() * 18) + 's;animation-delay:-' + (Math.random() * 30) + 's;' +
      '--dx:' + (Math.random() * 80 - 40) + 'px';
    box.appendChild(b);
  }
})();
