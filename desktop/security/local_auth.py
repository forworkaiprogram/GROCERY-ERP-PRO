"""Local Windows authentication for the desktop app.

PBKDF2-SHA256 with per-user random salt (stdlib only; no third-party
dependency on the desktop). Roles gate navigation (RBAC) and every login
is recorded in the local audit log.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid as uuidlib

from ..database.db import Database

ROLES = ("admin", "manager", "cashier", "accountant")
ITERATIONS = 200_000


class LocalAuthError(ValueError):
    pass


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), ITERATIONS
    )
    return digest.hex()


class LocalAuth:
    def __init__(self, db: Database):
        self.db = db

    # ---- provisioning ----------------------------------------------------
    def ensure_default_admin(self) -> dict | None:
        """Seed the first admin account only when none exist. Returns the
        created row or None. The password MUST be changed on first login
        (enforced by the UI warning; documented in the runbook)."""
        row = self.db.query_one(
            "SELECT uuid FROM local_users WHERE role='admin' LIMIT 1"
        )
        if row:
            return None
        return self.create_user(
            username="admin", name="مدير النظام", role="admin",
            password="admin123",
        )

    def create_user(self, *, username: str, name: str, role: str,
                    password: str) -> dict:
        if role not in ROLES:
            raise LocalAuthError(f"unknown role {role!r}")
        if not username or not password:
            raise LocalAuthError("username and password are required")
        if len(password) < 6:
            raise LocalAuthError("password must be at least 6 characters")
        salt = secrets.token_hex(16)
        uuid_value = str(uuidlib.uuid4())
        try:
            self.db.execute(
                "INSERT INTO local_users (uuid, username, name, role,"
                " password_hash, salt) VALUES (?,?,?,?,?,?)",
                (uuid_value, username.strip(), name or username, role,
                 _hash_password(password, salt), salt),
            )
        except Exception as exc:
            raise LocalAuthError(f"cannot create user: {exc}") from exc
        return {"uuid": uuid_value, "username": username.strip(),
                "name": name or username, "role": role}

    # ---- login ------------------------------------------------------------
    def login(self, username: str, password: str) -> dict:
        row = self.db.query_one(
            "SELECT uuid, username, name, role, password_hash, salt, status"
            " FROM local_users WHERE username=?",
            ((username or "").strip(),),
        )
        if row is None:
            raise LocalAuthError("اسم المستخدم أو كلمة المرور غير صحيحة")
        if row["status"] != "ACTIVE":
            raise LocalAuthError("هذا الحساب معطل")
        expected = row["password_hash"]
        if not hmac.compare_digest(
            _hash_password(password or "", row["salt"]), expected
        ):
            self.db.execute(
                "INSERT INTO audit_log (user_id, action, target_uuid, detail)"
                " VALUES (?,'auth.login_failed', NULL, ?)",
                (row["uuid"], username),
            )
            raise LocalAuthError("اسم المستخدم أو كلمة المرور غير صحيحة")
        self.db.execute(
            "INSERT INTO audit_log (user_id, action, target_uuid)"
            " VALUES (?,'auth.login', ?)",
            (row["uuid"], row["uuid"]),
        )
        return {"uuid": row["uuid"], "username": row["username"],
                "name": row["name"], "role": row["role"]}

    # ---- administration -----------------------------------------------------
    def list_users(self) -> list[dict]:
        return [
            {"uuid": r["uuid"], "username": r["username"], "name": r["name"],
             "role": r["role"], "status": r["status"],
             "created_at": r["created_at"]}
            for r in self.db.query_all(
                "SELECT uuid, username, name, role, status, created_at"
                " FROM local_users ORDER BY username"
            )
        ]

    def set_password(self, username: str, new_password: str) -> None:
        if len(new_password) < 6:
            raise LocalAuthError("كلمة المرور يجب أن تكون 6 أحرف على الأقل")
        row = self.db.query_one(
            "SELECT uuid FROM local_users WHERE username=?", (username,)
        )
        if row is None:
            raise LocalAuthError("المستخدم غير موجود")
        self._update_password(row["uuid"], new_password)

    def reset_password(self, user_uuid: str, new_password: str) -> None:
        if len(new_password) < 6:
            raise LocalAuthError("كلمة المرور يجب أن تكون 6 أحرف على الأقل")
        self._update_password(user_uuid, new_password)

    def set_status(self, user_uuid: str, status: str) -> None:
        if status not in ("ACTIVE", "DISABLED"):
            raise LocalAuthError(f"invalid status {status!r}")
        row = self.db.query_one(
            "SELECT role FROM local_users WHERE uuid=?", (user_uuid,)
        )
        if row is None:
            raise LocalAuthError("المستخدم غير موجود")
        if row["role"] == "admin" and status == "DISABLED":
            admins = self.db.query_one(
                "SELECT COUNT(*) AS n FROM local_users WHERE role='admin'"
                " AND status='ACTIVE'"
            )
            if int(admins["n"]) <= 1:
                raise LocalAuthError("لا يمكن تعطيل آخر حساب مدير مفعّل")
        self.db.execute(
            "UPDATE local_users SET status=? WHERE uuid=?",
            (status, user_uuid),
        )

    def _update_password(self, user_uuid: str, new_password: str) -> None:
        salt = secrets.token_hex(16)
        self.db.execute(
            "UPDATE local_users SET password_hash=?, salt=? WHERE uuid=?",
            (_hash_password(new_password, salt), salt, user_uuid),
        )

    def audit(self, user, action: str, target_type: str | None = None,
              target_uuid: str | None = None, detail: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO audit_log (user_id, action, target_type, target_uuid,"
            " detail) VALUES (?,?,?,?,?)",
            (user["uuid"] if user else None, action, target_type,
             target_uuid, detail),
        )
