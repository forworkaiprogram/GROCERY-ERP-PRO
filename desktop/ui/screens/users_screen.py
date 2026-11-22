"""Users screen (admin-only): local users managed via LocalAuth."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QComboBox,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from .common import ListScreen


class UsersScreen(ListScreen):
    def __init__(self, runtime, language: str, user: dict | None = None):
        super().__init__(runtime, language)
        self.user = user or {}
        self._setup_table(["username", "name", "role", "status", "created"])

        actions = QHBoxLayout()
        add = QPushButton(tr(language, "add_user"))
        add.clicked.connect(self._add_dialog)
        self.reset_btn = QPushButton(tr(language, "reset_password"))
        self.reset_btn.clicked.connect(self._reset_password)
        self.toggle_btn = QPushButton(tr(language, "disable"))
        self.toggle_btn.clicked.connect(self._toggle_status)
        actions.addWidget(add)
        actions.addWidget(self.reset_btn)
        actions.addWidget(self.toggle_btn)
        actions.addStretch(1)
        self.layout().addLayout(actions)
        self.reload()

    def reload(self) -> None:
        users = self.runtime.local_auth.list_users()
        self._uuids = [u["uuid"] for u in users]
        self._users = users
        self._show_rows([
            [u["username"], u["name"], u["role"], u["status"],
             (u["created_at"] or "")[:19]]
            for u in users
        ])

    def _selected_user(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._uuids):
            return None
        return self._users[row]

    def _add_dialog(self) -> None:
        dialog = QWidget(self)
        dialog.setWindowTitle(tr(self.language, "add_user"))
        dialog.setMinimumWidth(380)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        username = QLineEdit()
        name = QLineEdit()
        password = QLineEdit()
        password.setEchoMode(QLineEdit.Password)
        role = QComboBox()
        role.addItems(["cashier", "accountant", "manager", "admin"])
        form.addRow(tr(self.language, "username"), username)
        form.addRow(tr(self.language, "name"), name)
        form.addRow(tr(self.language, "password"), password)
        form.addRow(tr(self.language, "role"), role)
        layout.addLayout(form)

        def submit() -> None:
            if not username.text().strip() or not password.text():
                QMessageBox.warning(
                    self, tr(self.language, "error"),
                    tr(self.language, "enter_all_fields"),
                )
                return
            try:
                self.runtime.local_auth.create_user(
                    username=username.text().strip(),
                    name=name.text().strip() or username.text().strip(),
                    role=role.currentText(),
                    password=password.text(),
                )
            except Exception as exc:
                QMessageBox.critical(self, tr(self.language, "error"), str(exc))
                return
            dialog.close()
            self.reload()

        buttons = QHBoxLayout()
        save = QPushButton(tr(self.language, "save"))
        save.clicked.connect(submit)
        cancel = QPushButton(tr(self.language, "cancel"))
        cancel.clicked.connect(dialog.close)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        dialog.show()

    def _reset_password(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        dialog = QWidget(self)
        dialog.setWindowTitle(tr(self.language, "reset_password"))
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        password = QLineEdit()
        password.setEchoMode(QLineEdit.Password)
        form.addRow(tr(self.language, "new_password"), password)
        layout.addLayout(form)

        def submit() -> None:
            try:
                self.runtime.local_auth.reset_password(
                    user["uuid"], password.text()
                )
            except Exception as exc:
                QMessageBox.critical(self, tr(self.language, "error"), str(exc))
                return
            QMessageBox.information(
                self, tr(self.language, "users"),
                tr(self.language, "password_changed"),
            )
            dialog.close()

        buttons = QHBoxLayout()
        save = QPushButton(tr(self.language, "save"))
        save.clicked.connect(submit)
        cancel = QPushButton(tr(self.language, "cancel"))
        cancel.clicked.connect(dialog.close)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        dialog.show()

    def _toggle_status(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        try:
            new_status = "DISABLED" if user["status"] == "ACTIVE" else "ACTIVE"
            self.runtime.local_auth.set_status(user["uuid"], new_status)
        except Exception as exc:
            QMessageBox.critical(self, tr(self.language, "error"), str(exc))
            return
        self.reload()
