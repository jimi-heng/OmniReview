from __future__ import annotations

import hashlib

from werkzeug.security import check_password_hash, generate_password_hash

from grpfh.database import connect

from . import bp
from ._context import get_settings
from ._helpers import fail, json_body, ok


def _is_legacy_md5(value: str) -> bool:
    if len(value) != 32:
        return False
    try:
        int(value, 16)
        return True
    except Exception:
        return False


def _verify_password(stored: str, provided: str) -> tuple[bool, bool]:
    # Returns (match, should_upgrade).
    if _is_legacy_md5(stored):
        return hashlib.md5(provided.encode()).hexdigest() == stored, True
    return check_password_hash(stored, provided), False


@bp.get("/test")
def test():
    return ok("Python后端运行正常！")


@bp.post("/login")
def login():
    data = json_body()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return fail("Email and password cannot be empty")

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, password FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        if not user:
            return fail("Incorrect email or password")

        stored = str(user["password"] or "")
        match, should_upgrade = _verify_password(stored, password)
        if not match:
            return fail("Incorrect email or password")

        if should_upgrade:
            # Transparent migration: MD5 -> modern salted hash.
            cursor.execute(
                "UPDATE users SET password = ? WHERE id = ?",
                (generate_password_hash(password), user["id"]),
            )
            conn.commit()

    return ok(
        "Login successful",
        user_id=user["id"],
        email=user["email"],
    )


@bp.post("/register")
def register():
    data = json_body()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return fail("Email and password are required!")
    if len(str(password)) < 6:
        return fail("Password must be at least 6 characters!")

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM users WHERE email = ?", (email,))
        if cursor.fetchone():
            return fail("Email already registered!")

        cursor.execute(
            "INSERT INTO users (email, password) VALUES (?, ?)",
            (email, generate_password_hash(password)),
        )
        conn.commit()

    return ok("Register success!")


@bp.post("/change-password")
def change_password():
    data = json_body()
    user_id = data.get("user_id")
    current_pwd = data.get("current_password")
    new_pwd = data.get("new_password")

    if not user_id or not current_pwd or not new_pwd:
        return fail("Missing fields", status=400)

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return fail("User not found", status=404)

        stored = str(row["password"] or "")
        match, _ = _verify_password(stored, current_pwd)
        if not match:
            return fail("Incorrect current password", status=401)

        cursor.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (generate_password_hash(new_pwd), user_id),
        )
        conn.commit()

    return ok("Password updated successfully")

