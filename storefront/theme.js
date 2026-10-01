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
