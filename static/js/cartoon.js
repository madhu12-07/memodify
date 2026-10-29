/* Swaps emoji characters for cute cartoon icons (pure visual layer: the text/data underneath is untouched). */
(function () {
  'use strict';
  var HAVE = '1f308 1f389 1f3a4 1f3a7 1f3af 1f3b5 1f3b6 1f3b8 1f3b9 1f3e0 1f441 1f44b 1f494 1f4a1 1f4aa 1f4ad 1f4d6 1f4f7 1f4fb 1f500 1f501 1f525 1f558 1f602 1f604 1f60a 1f60c 1f60d 1f610 1f618 1f620 1f621 1f622 1f628 1f62d 1f634 1f632 1f642 1f680 1f6aa 1f90d 1f929 1f973 1f92c 1f922 1f970 1f9d8 1faa2 2728 2753 2764'.split(' ');
  var SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, INPUT: 1, OPTION: 1, TITLE: 1, NOSCRIPT: 1 };
  var me = document.currentScript;
  var base = me && me.src ? me.src.replace(/js\/[^\/]*$/, 'img/cartoon/') : '/static/img/cartoon/';
  // some emoji look the same as one we drew
  var ALIAS = { '1f60e': '1f604' };
  var RX = /(?:[❤✨❓]|[\ud83c-\ud83e][\udc00-\udfff])️?/g;

  function codeOf(ch) {
    var cp = ch.codePointAt(0).toString(16);
    return ALIAS[cp] || cp;
  }
  function icon(code, ch) {
    var i = document.createElement('img');
    i.className = 'cx'; i.src = base + code + '.svg'; i.alt = ''; i.setAttribute('aria-hidden', 'true');
    i.draggable = false; i.setAttribute('data-emoji', ch);
    return i;
  }
  function convert(node) {
    var text = node.nodeValue;
    if (!text || !RX.test(text)) { RX.lastIndex = 0; return; }
    RX.lastIndex = 0;
    var frag = document.createDocumentFragment(), last = 0, m, changed = false;
    while ((m = RX.exec(text))) {
      var code = codeOf(m[0]);
      if (HAVE.indexOf(code) < 0) continue;
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      frag.appendChild(icon(code, m[0]));
      last = m.index + m[0].length; changed = true;
    }
    if (!changed) return;
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    node.parentNode.replaceChild(frag, node);
  }
  function walk(root) {
    if (root.nodeType === 3) { if (root.parentNode && !SKIP[root.parentNode.nodeName]) convert(root); return; }
    if (root.nodeType !== 1 || SKIP[root.nodeName]) return;
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null), list = [], n;
    while ((n = w.nextNode())) { if (!SKIP[n.parentNode.nodeName]) list.push(n); }
    list.forEach(convert);
  }
  function start() {
    walk(document.body);
    new MutationObserver(function (muts) {
      muts.forEach(function (mu) {
        if (mu.type === 'characterData') walk(mu.target);
        mu.addedNodes.forEach(walk);
      });
    }).observe(document.body, { childList: true, characterData: true, subtree: true });
  }
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
