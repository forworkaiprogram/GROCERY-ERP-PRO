"""Qt worker threads for background sync and update checks.

Runs OUTSIDE the UI thread; communicates via Qt signals only. The SQLite
engine serializes writes through its RLock, so a running sync never blocks
or corrupts POS writes.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, Signal


class SyncWorkerSignals(QObject):
    cycleCompleted = Signal(dict)
    connectivityChanged = Signal(bool)


class SyncWorker(QObject):
    """Owns a SyncEngine on its own thread. Interval-driven; the UI remains
    free — a sale committed during a cycle is picked up in the next cycle.
    Triggered immediately when connectivity returns."""

    def __init__(self, engine, interval_seconds: int = 30):
        super().__init__()
        self.engine = engine
        self.interval = interval_seconds
        self.signals = SyncWorkerSignals()
        self._was_online = None
        self._running = False

    def run_forever(self) -> None:
        self._running = True
        logger = logging.getLogger("groceryerp.sync")
        while self._running and not self.engine._stop.is_set():
            try:
                online = self.engine.transport.check_connectivity()
            except Exception:
                online = False
            if online != self._was_online:
                self.signals.connectivityChanged.emit(online)
                self._was_online = online
            if online:
                try:
                    result = self.engine.run_once()
                    if result.get("submitted"):
                        self.signals.cycleCompleted.emit(result)
                except Exception as exc:
                    logger.error("sync cycle failed: %s", exc)
            time.sleep(self.interval)

    def stop(self) -> None:
        self._running = False
        self.engine.stop()


class UpdateCheckWorker(QObject):
    finished = Signal(object, str)

    def __init__(self, service, channel: str = "stable"):
        super().__init__()
        self.service = service
        self.channel = channel

    def run(self) -> None:
        try:
            manifest = self.service.check_for_updates(self.channel)
            self.finished.emit(manifest, "")
        except Exception as exc:
            self.finished.emit(None, str(exc))
