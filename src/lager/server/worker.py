"""Arbeiter für Vorschläge: bereitet sie im Hintergrund vor, einen nach dem anderen.

Der Server startet ihn beim Hochfahren (lifespan in app.create_app) und hält ihn beim
Beenden an. Ein neuer Vorschlag weckt ihn sofort (`wake`). Zusätzlich schaut er alle
`interval` Sekunden nach wartenden Vorschlägen, etwa nach einem Neustart oder wenn ein
anderes Programm einen angelegt hat.

Einer nach dem anderen, weil die späteren Stufen eine Grafikkarte (lokales Sprachmodell) und
eine Schnittstelle mit Aufrufgrenze (Mouser) teilen. Die Tests starten den Arbeiter nicht,
sondern rufen `run_once` selbst auf; so läuft dort nichts nebenläufig.
"""
from __future__ import annotations

import logging
import threading

from .. import drafts as draftmod

log = logging.getLogger("lager.vorschlaege")


class DraftWorker:
    def __init__(self, app, interval: float = 30.0):
        self.app = app
        self.interval = interval
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="lager-vorschlaege", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def wake(self) -> None:
        """Sofort nach wartenden Vorschlägen schauen (nach dem Anlegen eines Vorschlags)."""
        self._wake.set()

    def run_once(self) -> int:
        """Bereitet alle wartenden Vorschläge des aktuellen Lagers vor."""
        state = self.app.state
        return draftmod.process_pending(state.root, state.cfg, self._stop.is_set)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()  # vor der Arbeit: Ein Wecken währenddessen geht nicht verloren
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - der Arbeiter soll weiterlaufen
                log.exception("Vorschläge vorbereiten ist fehlgeschlagen")
            self._wake.wait(self.interval)
