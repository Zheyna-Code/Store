// Переключатель светлой/тёмной темы. Выбор хранится в localStorage.
(function () {
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem('nexus-theme'); } catch (e) {}
  root.dataset.theme = saved === 'dark' ? 'dark' : 'light';
  function sync(button) {
    var dark = root.dataset.theme === 'dark';
    button.setAttribute('aria-pressed', dark ? 'true' : 'false');
    button.setAttribute('aria-label', dark ? 'Включить светлую тему' : 'Включить тёмную тему');
  }
  document.addEventListener('DOMContentLoaded', function () {
    var button = document.getElementById('theme-toggle');
    if (!button) return;
    sync(button);
    button.addEventListener('click', function () {
      root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem('nexus-theme', root.dataset.theme); } catch (e) {}
      sync(button);
    });
  });
})();

// 3D-наклон кнопки «Перейти в каталог» за курсором (только мышь/перо).
(function () {
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  document.addEventListener('DOMContentLoaded', function () {
    var cta = document.querySelector('.cta');
    if (!cta) return;
    var MAX = 12;
    cta.addEventListener('pointermove', function (e) {
      if (e.pointerType === 'touch') return;
      var r = cta.getBoundingClientRect();
      var x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      cta.classList.add('tilting');
      cta.style.setProperty('--ry', ((x - 0.5) * 2 * MAX).toFixed(2) + 'deg');
      cta.style.setProperty('--rx', ((0.5 - y) * 2 * MAX * 0.7).toFixed(2) + 'deg');
      cta.style.setProperty('--mx', (x * 100).toFixed(1) + '%');
      cta.style.setProperty('--my', (y * 100).toFixed(1) + '%');
    });
    cta.addEventListener('pointerleave', function () {
      cta.classList.remove('tilting');
      cta.style.setProperty('--rx', '0deg');
      cta.style.setProperty('--ry', '0deg');
      cta.style.setProperty('--mx', '50%');
      cta.style.setProperty('--my', '50%');
    });
  });
})();

// Свет под курсором на маленьких кнопках шапки.
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var buttons = document.querySelectorAll('.login, .tg, .theme');
    Array.prototype.forEach.call(buttons, function (b) {
      b.addEventListener('pointermove', function (e) {
        var r = b.getBoundingClientRect();
        b.style.setProperty('--mx', ((e.clientX - r.left) / r.width * 100).toFixed(1) + '%');
        b.style.setProperty('--my', ((e.clientY - r.top) / r.height * 100).toFixed(1) + '%');
      });
    });
  });
})();

// Разделы «Главная» / «Каталог» (переключение по #catalog без перезагрузки, с анимацией).
(function () {
  var timer = null;
  function views() { return { home: document.getElementById('home'), catalog: document.getElementById('catalog') }; }
  function mark(name) {
    document.documentElement.dataset.view = name;
    Array.prototype.forEach.call(document.querySelectorAll('.nav a'), function (a) {
      var on = a.dataset.view === name;
      a.classList.toggle('active', on);
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
  }
  function show(animate) {
    var v = views(); if (!v.home || !v.catalog) return;
    var name = location.hash === '#catalog' ? 'catalog' : 'home';
    var to = v[name], from = v[name === 'catalog' ? 'home' : 'catalog'];
    mark(name);
    clearTimeout(timer);
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    function enter() {
      from.hidden = true; from.classList.remove('view-out');
      to.hidden = false;
      if (animate && !reduce) {
        to.classList.remove('view-in'); void to.offsetWidth; to.classList.add('view-in');
        timer = setTimeout(function () { to.classList.remove('view-in'); }, 950);
      }
    }
    if (animate && !reduce && !from.hidden) {
      to.classList.remove('view-in');
      from.classList.add('view-out');
      timer = setTimeout(enter, 300);
    } else enter();
  }
  document.addEventListener('DOMContentLoaded', function () { show(false); });
  window.addEventListener('hashchange', function () { show(true); });
})();
