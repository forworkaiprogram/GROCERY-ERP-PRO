"""Application entry point (EXE target).

Initializes the Qt-free runtime first (migrations, device identity), then
starts the Qt UI and background workers. If Qt cannot start (missing
platform plugins), the app exits with a clear error instead of running
degraded business logic.
"""

from __future__ import annotations

import logging
import os
import sys


def main() -> int:
    logging.basicConfig(level=logging.INFO)

    from ..app.bootstrap import DesktopRuntime

    runtime = DesktopRuntime()
    runtime.initialize()
    if not runtime.db.integrity_check():
        logging.critical("local database failed integrity check at startup")
        return 2

    try:
        from PySide6.QtCore import QThread, Qt
        from PySide6.QtWidgets import QApplication

        from ..ui.main_window import MainWindow
        from ..ui.sync_workers import SyncWorker
    except ImportError as exc:
        logging.critical("Qt unavailable in this environment: %s", exc)
        return 3

    app = QApplication(sys.argv)
    app.setApplicationName("GROCERY ERP PRO")
    language = language_from_config(runtime)
    window = MainWindow(runtime, language=language)
    window.show()

    sync_engine = runtime.build_sync_engine()
    worker = SyncWorker(sync_engine)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run_forever)
    app.aboutToQuit.connect(worker.stop)
    app.aboutToQuit.connect(thread.quit)
    thread.start()

    exit_code = app.exec()
    runtime.shutdown()
    return exit_code


def language_from_config(runtime) -> str:
    row = runtime.db.query_one(
        "SELECT value FROM app_config WHERE key='language'"
    )
    return row["value"] if row else "ar"


if __name__ == "__main__":
    raise SystemExit(main())
