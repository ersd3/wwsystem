// Komfort für die Seiten. Ohne JavaScript geht alles weiter über normale Formulare:
// Suchen mit dem Knopf, Hochladen mit dem Knopf, den Pfad zum Lager von Hand eintippen.

// Zeigt den Seiten, dass JavaScript läuft (style.css: .jsonly und .nojs).
document.documentElement.classList.add('js');

// Suche beim Tippen: lädt die Trefferliste nach, ohne die Seite neu zu laden.
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

// Vorschläge auf /neu: Solange einer wartet oder in Arbeit ist (data-pending), die Liste
// alle 3 Sekunden neu laden. Ist keiner mehr offen, hört das Nachladen auf.
(function () {
  if (!window.fetch) return;

  function schedule() {
    var box = document.getElementById('vorschlaege');
    if (!box || !box.hasAttribute('data-pending')) return;
    setTimeout(function () {
      fetch(box.getAttribute('data-poll'))
        .then(function (response) {
          return response.ok ? response.text() : Promise.reject(response.status);
        })
        .then(function (html) {
          var current = document.getElementById('vorschlaege');
          if (current) current.outerHTML = html;
        })
        .catch(function () {
          // Server kurz nicht erreichbar: beim nächsten Mal wieder versuchen.
        })
        .then(schedule);
    }, 3000);
  }

  schedule();
})();

// Unterkategorie: nur die der gewählten Kategorie zur Auswahl stellen.
// Der Server liefert alle als <option data-kategorie="..." data-kurz="...">.
(function () {
  var sub = document.getElementById('unterkategorie');
  var cat = document.getElementById('kategorie');
  if (!sub || !cat) return;

  var all = [];
  for (var i = 0; i < sub.options.length; i++) {
    var option = sub.options[i];
    if (!option.value) continue;
    all.push({
      value: option.value,
      kategorie: option.getAttribute('data-kategorie'),
      kurz: option.getAttribute('data-kurz'),
      lang: option.text
    });
  }

  function fill() {
    var chosen = sub.value;
    while (sub.options.length > 1) sub.remove(1); // "– keine –" bleibt stehen
    all.forEach(function (entry) {
      if (cat.value && entry.kategorie !== cat.value) return;
      sub.add(new Option(cat.value ? entry.kurz : entry.lang, entry.value));
    });
    sub.value = chosen;
    if (sub.selectedIndex < 0) sub.value = ''; // gehörte zur vorigen Kategorie
  }

  cat.addEventListener('change', fill);
  fill();
})();

// Rückfrage vor dem Absenden: <form data-confirm="Wirklich löschen?">.
document.addEventListener('submit', function (event) {
  var form = event.target;
  var question = form && form.getAttribute && form.getAttribute('data-confirm');
  if (question && !window.confirm(question)) event.preventDefault();
});

// Hochladen gleich nach der Auswahl der Dateien, mit Fortschrittsbalken:
// <form data-auto-upload> mit einem Dateifeld und einem Block .upload-status.
(function () {
  if (!window.XMLHttpRequest || !window.FormData) return;

  function upload(form, input) {
    var box = form.querySelector('.upload-status');
    var bar = box && box.querySelector('progress');
    var text = box && box.querySelector('.upload-text');
    var number = input.files ? input.files.length : 0;
    if (!box || !number) return;

    var label = number === 1 ? '1 Datei' : number + ' Dateien';
    var data = new FormData(form); // vor dem Sperren: gesperrte Felder fehlen sonst
    var request = new XMLHttpRequest();

    function failed(message) {
      input.disabled = false;
      input.value = '';
      bar.value = 0;
      text.textContent = message;
    }

    box.hidden = false;
    input.disabled = true;
    bar.value = 0;
    text.textContent = label + ' · 0 %';

    request.upload.addEventListener('progress', function (event) {
      if (!event.lengthComputable) return;
      var percent = Math.floor((event.loaded / event.total) * 100);
      bar.value = percent;
      text.textContent = percent < 100 ? label + ' · ' + percent + ' %' : 'Wird gespeichert …';
    });
    request.addEventListener('load', function () {
      // Erfolg: Der Server leitet auf die Bauteilseite mit der Meldung "hochgeladen" weiter.
      var landed = (request.responseURL || '').split('?')[0];
      if (request.status === 200 && landed && landed !== form.action.split('?')[0]) {
        window.location.replace(request.responseURL);
        return;
      }
      // Fehler: Die Antwort ist die Bauteilseite mit der Fehlermeldung; ihren Inhalt übernehmen.
      var page = request.response;
      var fresh = page && page.querySelector ? page.querySelector('main') : null;
      var main = document.querySelector('main');
      if (fresh && main) {
        main.innerHTML = fresh.innerHTML;
        window.scrollTo(0, 0);
      } else if (request.status === 403) {
        failed('Der Schreibschutz ist aktiv. Bitte zuerst anmelden.');
      } else {
        failed('Hochladen fehlgeschlagen (Fehler ' + request.status + ').');
      }
    });
    request.addEventListener('error', function () {
      failed('Hochladen fehlgeschlagen. Verbindung zum Server prüfen und noch einmal versuchen.');
    });
    request.addEventListener('abort', function () {
      failed('Hochladen abgebrochen.');
    });

    request.open('POST', form.action);
    request.responseType = 'document';
    request.send(data);
  }

  // Auf dem Dokument lauschen: gilt auch, nachdem der Seiteninhalt ersetzt wurde.
  document.addEventListener('change', function (event) {
    var input = event.target;
    if (!input || input.type !== 'file' || !input.form) return;
    if (input.form.hasAttribute('data-auto-upload')) upload(input.form, input);
  });
})();

// Lager-Ordner auswählen: Der Server öffnet am PC das Ordner-Auswahlfenster und
// liefert den Pfad, der dann im Eingabefeld steht. Umgestellt wird erst mit "Übernehmen".
document.addEventListener('click', function (event) {
  var button = event.target.closest ? event.target.closest('[data-pick-folder]') : null;
  if (!button || !window.fetch) return;

  var input = document.getElementById(button.getAttribute('data-target'));
  var status = document.getElementById(button.getAttribute('data-status'));
  var problem = 'Das Auswahlfenster ließ sich nicht öffnen. Bitte den Pfad eintippen.';

  button.disabled = true;
  status.textContent =
    'Das Auswahlfenster ist an diesem PC geöffnet. Falls es nicht zu sehen ist, liegt es hinter dem Browser.';
  fetch(button.getAttribute('data-pick-folder'), { method: 'POST' })
    .then(function (response) {
      return response.json().then(function (data) {
        return { ok: response.ok, data: data };
      });
    })
    .then(function (result) {
      if (!result.ok) {
        status.textContent = result.data.detail || problem;
      } else if (result.data.pfad) {
        input.value = result.data.pfad;
        status.textContent = 'Ordner gewählt. Mit „Übernehmen“ wird er eingestellt.';
      } else {
        status.textContent = 'Kein Ordner ausgewählt.';
      }
    })
    .catch(function () {
      status.textContent = problem;
    })
    .then(function () {
      button.disabled = false;
    });
});
