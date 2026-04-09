import secrets
from typing import Protocol

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher


class PasswordHelperProtocol(Protocol):
    def verify_and_update(
        self, plain_password: str, hashed_password: str
    ) -> tuple[bool, str | None]: ...  # pragma: no cover

    def hash(self, password: str) -> str: ...  # pragma: no cover

    def generate(self) -> str: ...  # pragma: no cover


class PasswordHelper(PasswordHelperProtocol):
    def __init__(self, password_hash: PasswordHash | None = None) -> None:
        if password_hash is None:
            self.password_hash = PasswordHash(
                (
                    Argon2Hasher(),
                    BcryptHasher(),
                )
            )
        else:
            self.password_hash = password_hash  # pragma: no cover

    def verify_and_update(
        self, plain_password: str, hashed_password: str
    ) -> tuple[bool, str | None]:
        return self.password_hash.verify_and_update(plain_password, hashed_password)

    def hash(self, password: str) -> str:
        return self.password_hash.hash(password)

    def generate(self) -> str:
        return secrets.token_urlsafe()
