// Suche beim Tippen: lädt die Trefferliste nach, ohne die Seite neu zu laden.
// Ohne JavaScript funktioniert die Suche weiter über den Knopf "Suchen".
(function () {
  var input = document.querySelector('.search input[name="q"]');
  var target = document.getElementById('treffer');
  if (!input || !target || !window.fetch) return;

  var timer = null;
  var latest = 0;

  input.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var params = new URLSearchParams(new FormData(input.form)).toString();
      var mine = ++latest;
      fetch('/suche?' + params)
        .then(function (response) {
          return response.ok ? response.text() : Promise.reject(response.status);
        })
        .then(function (html) {
          if (mine !== latest) return; // eine neuere Eingabe ist schon unterwegs
          target.innerHTML = html;
          history.replaceState(null, '', '/?' + params);
        })
        .catch(function () {
          // Bei einem Fehler bleibt die alte Liste stehen; der Knopf "Suchen" geht weiter.
        });
    }, 200);
  });
})();
