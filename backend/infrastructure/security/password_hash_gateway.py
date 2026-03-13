"""Password hashing gateway."""

from __future__ import annotations

import bcrypt


class PasswordHashGateway:
    def hash_password(self, password: str) -> str:
        salt = bcrypt.gensalt(rounds=12)
        password_hash = bcrypt.hashpw(password.encode("utf-8"), salt)
        return password_hash.decode("utf-8")

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except Exception:
            return False
