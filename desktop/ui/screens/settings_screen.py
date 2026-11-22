"""Settings screen: store config + local backups + password change.

Config rows persist in app_config (never overwritten by updates — the
data directory is separate from the executable). Backups use the tested
LocalBackupManager (SHA-256 sidecar, integrity-checked restore).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr

CONFIG_FIELDS = [
    ("store_name", "store_name"),
    ("currency", "currency"),
    ("language", "language"),
    ("theme", "night_mode"),
]


class SettingsScreen(QWidget):
    def __init__(self, runtime, language: str, user: dict | None = None):
        super().__init__()
        self.runtime = runtime
        self.language = language
        self.user = user or {}

        layout = QVBoxLayout(self)
        header = QLabel(f"⚙ {tr(language, 'settings')}")
        header.setObjectName("pageHeader")
        layout.addWidget(header)

        warning = QLabel(tr(language, "default_admin_warning"))
        warning.setObjectName("warningCard")
        warning.setWordWrap(True)
        if not self._default_password_active():
            warning.hide()
        layout.addWidget(warning)
        self._warning = warning

        config_form = QFormLayout()
        self.inputs: dict[str, QLineEdit] = {}
        for key, label in CONFIG_FIELDS:
            edit = QLineEdit(self._config_value(key))
            self.inputs[key] = edit
            if key == "theme":
                continue
            config_form.addRow(tr(language, label), edit)
        self.inputs.pop("theme", None)
        save_cfg = QPushButton(tr(language, "save"))
        save_cfg.clicked.connect(self._save_config)
        config_form.addRow(save_cfg)
        layout.addLayout(config_form)

        note = QLabel(tr(language, "language_note"))
        note.setWordWrap(True)
        layout.addWidget(note)

        pw_row = QHBoxLayout()
        self.old_pw = QLineEdit()
        self.old_pw.setEchoMode(QLineEdit.Password)
        self.new_pw = QLineEdit()
        self.new_pw.setEchoMode(QLineEdit.Password)
        pw_form = QFormLayout()
        pw_form.addRow(tr(language, "old_password"), self.old_pw)
        pw_form.addRow(tr(self.language, "new_password"), self.new_pw)
        pw_row.addLayout(pw_form)
        change = QPushButton(tr(language, "change_password"))
        change.clicked.connect(self._change_password)
        pw_row.addWidget(change)
        layout.addLayout(pw_row)

        layout.addWidget(QLabel(tr(language, "backups")))
        self.backups_table = QTableWidget(0, 2)
        self.backups_table.setHorizontalHeaderLabels([
            tr(language, "created"), tr(language, "file"),
        ])
        self.backups_table.setEditTriggers(QTableWidget.NoEditTriggers)
        if language == "ar":
            self.backups_table.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(self.backups_table, 3)

        backup_btns = QHBoxLayout()
        create_btn = QPushButton(tr(language, "create_backup"))
        create_btn.clicked.connect(self._create_backup)
        restore_btn = QPushButton(tr(language, "restore_backup"))
        restore_btn.clicked.connect(self._restore_backup)
        backup_btns.addWidget(create_btn)
        backup_btns.addWidget(restore_btn)
        backup_btns.addStretch(1)
        layout.addLayout(backup_btns)
        self.reload()

    # ---- config ------------------------------------------------------------
    def _config_value(self, key: str) -> str:
        row = self.runtime.db.query_one(
            "SELECT value FROM app_config WHERE key=?", (key,)
        )
        return row["value"] if row else ""

    def _save_config(self) -> None:
        for key in ("store_name", "currency", "language"):
            value = self.inputs[key].text().strip()
            if key == "language" and value not in ("ar", "en", ""):
                QMessageBox.warning(
                    self, tr(self.language, "error"),
                    tr(self.language, "enter_all_fields"),
                )
                return
            if value == "":
                continue
            self.runtime.db.execute(
                "INSERT INTO app_config (key, value) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        QMessageBox.information(
            self, tr(self.language, "settings"), tr(self.language, "saved")
        )

    def _default_password_active(self) -> bool:
        try:
            from ...security.local_auth import _hash_password

            row = self.runtime.db.query_one(
                "SELECT password_hash, salt FROM local_users WHERE username='admin'"
            )
            if not row:
                return False
            return _hash_password("admin123", row["salt"]) == row["password_hash"]
        except Exception:
            return False

    # ---- password ------------------------------------------------------------
    def _change_password(self) -> None:
        current = self.old_pw.text()
        new = self.new_pw.text()
        try:
            self.runtime.local_auth.login(
                self.user.get("username") or "", current
            )
        except Exception:
            QMessageBox.critical(
                self, tr(self.language, "error"),
                tr(self.language, "old_password_wrong"),
            )
            return
        try:
            self.runtime.local_auth.set_password(
                self.user.get("username") or "", new
            )
        except Exception as exc:
            QMessageBox.critical(self, tr(self.language, "error"), str(exc))
            return
        QMessageBox.information(
            self, tr(self.language, "settings"),
            tr(self.language, "password_changed"),
        )
        self.old_pw.clear()
        self.new_pw.clear()
        self._warning.hide()

    # ---- backups ------------------------------------------------------------
    def reload(self) -> None:
        backups = self.runtime.backup.list_backups()
        self.backups_table.setRowCount(len(backups))
        for r, path in enumerate(backups):
            name = path.name.replace("groceryerp-", "").replace(".db", "")
            for c, value in enumerate([name, path.name]):
                item = QTableWidgetItem(value)
                self.backups_table.setItem(r, c, item)

    def _create_backup(self) -> None:
        try:
            path = self.runtime.backup.create(label="manual")
        except Exception as exc:
            QMessageBox.critical(self, tr(self.language, "error"), str(exc))
            return
        QMessageBox.information(
            self, tr(self.language, "backups"),
            f"{tr(self.language, 'backup_created')}: {path.name}",
        )
        self.reload()

    def _restore_backup(self) -> None:
        row = self.backups_table.currentRow()
        if row < 0 or row >= len(self.runtime.backup.list_backups()):
            QMessageBox.warning(
                self, tr(self.language, "error"),
                tr(self.language, "choose_backup"),
            )
            return
        path = self.runtime.backup.list_backups()[row]
        try:
            self.runtime.backup.restore(path)
        except Exception as exc:
            QMessageBox.critical(
                self, tr(self.language, "error"),
                f"{type(exc).__name__}: {exc}",
            )
            return
        QMessageBox.information(
            self, tr(self.language, "backups"),
            tr(self.language, "backup_restored"),
        )
