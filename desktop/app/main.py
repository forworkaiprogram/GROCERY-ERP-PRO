"""Application entry point (EXE target).

Initializes the Qt-free runtime first (migrations, device identity,
local auth), then shows the local login dialog (PBKDF2, offline), then
starts the themed main window and background workers. If Qt cannot
start, the app exits with a clear error instead of running degraded.
"""

from __future__ import annotations

import logging
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
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication

        from ..ui.sync_workers import SyncWorker
    except ImportError as exc:
        logging.critical("Qt unavailable in this environment: %s", exc)
        return 3

    app = QApplication(sys.argv)
    app.setApplicationName("GROCERY ERP PRO")

    from ..ui.theme import apply_theme, configured_theme

    theme = configured_theme(runtime.db)
    apply_theme(app, theme)

    from ..ui.login_dialog import LoginDialog
    from ..ui.main_window import MainWindow

    language = language_from_config(runtime)
    login = LoginDialog(runtime, language=language)
    if not login.exec():
        runtime.shutdown()
        return 0

    window = MainWindow(runtime, language=language, user=login.user)
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
