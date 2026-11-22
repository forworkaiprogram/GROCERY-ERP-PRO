"""Local login dialog backed by LocalAuth (PBKDF2, offline-capable).

Login runs entirely against the local users table: no cloud call blocks
the operator. Successful login returns a session user dict consumed by
MainWindow for RBAC and audit.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .i18n import tr


class LoginDialog(QDialog):
    def __init__(self, runtime, language: str = "ar"):
        super().__init__()
        self.runtime = runtime
        self.language = language
        self.user: dict | None = None
        self.setWindowTitle(tr(language, "login_title"))
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        logo = QLabel(f"🏪 {tr(language, 'app_title')}")
        logo.setObjectName("brandLabel")
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)

        form = QFormLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow(tr(language, "username"), self.username)
        form.addRow(tr(language, "password"), self.password)
        layout.addLayout(form)

        self.error = QLabel("")
        self.error.setStyleSheet("color:#b23b3b;")
        layout.addWidget(self.error)

        button = QPushButton(tr(language, "login"))
        button.setDefault(True)
        button.clicked.connect(self._login)
        layout.addWidget(button)
        if language == "ar":
            self.setLayoutDirection(Qt.RightToLeft)
        self.username.setFocus()

    def _login(self) -> None:
        self.error.setText("")
        try:
            user = self.runtime.local_auth.login(
                self.username.text().strip() or " ",
                self.password.text() or " ",
            )
        except Exception:
            user = None
        if user is None:
            self.error.setText(tr(self.language, "login_failed"))
            return
        self.user = dict(user)
        self.accept()
