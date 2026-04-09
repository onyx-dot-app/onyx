import re

try:
    import argon2.exceptions
    from argon2 import PasswordHasher
except ImportError as e:  # pragma: no cover
    from ..exceptions import HasherNotAvailable

    raise HasherNotAvailable("argon2") from e

from .base import HasherProtocol, ensure_str, validate_str_or_bytes

# Pattern for identifying and validating an Argon2 encoded hash, covering all currently
# supported type variants (i.e., `id`, `i`, `d`). Pattern uses deterministic matching,
# explicit anchors, and a non-greedy terminal quantifier to ensure linear run time
# relative to input hash length and resilience against catastrophic backtracking attacks.
ARGON2_ENCODED_HASH_REGEX: re.Pattern = re.compile(
    r"^\$(?P<variant>argon2(id|i|d))\$(?:v=(?P<version>\d+)\$)?"
    r"m=(?P<memory_cost>\d+),t=(?P<time_cost>\d+),p=(?P<parallelism>\d+)"
    r"(?:\$(?P<salt>[^$]+)(?:\$(?P<digest>.+?))?)?$"
)


class Argon2Hasher(HasherProtocol):
    def __init__(
        self,
        time_cost: int = argon2.DEFAULT_TIME_COST,
        memory_cost: int = argon2.DEFAULT_MEMORY_COST,
        parallelism: int = argon2.DEFAULT_PARALLELISM,
        hash_len: int = argon2.DEFAULT_HASH_LENGTH,
        salt_len: int = argon2.DEFAULT_RANDOM_SALT_LENGTH,
        type: argon2.Type = argon2.Type.ID,
    ) -> None:
        """

        Args:
            time_cost: Defines the amount of computation realized and
                therefore the execution time, given in number of iterations.
            memory_cost: Defines the memory usage, given in kibibytes.
            parallelism: Defines the number of parallel threads (*changes*
                the resulting hash value).
            hash_len: Length of the hash in bytes.
            salt_len: Length of random salt to be generated for each
                password.
            type: Argon2 type to use.  Only change for interoperability
                with legacy systems.

        """
        self._hasher = PasswordHasher(
            time_cost, memory_cost, parallelism, hash_len, salt_len, "utf-8", type
        )

    @classmethod
    def identify(cls, hash: str | bytes) -> bool:
        validate_str_or_bytes(hash, "hash")
        try:
            hash_str = ensure_str(hash)
        except UnicodeDecodeError:
            return False
        match = ARGON2_ENCODED_HASH_REGEX.fullmatch(hash_str)
        if match is None:
            return False
        variant: str = match.group("variant")
        return variant in {"argon2id", "argon2i", "argon2d"}

    def hash(self, password: str | bytes, *, salt: bytes | None = None) -> str:
        validate_str_or_bytes(password, "password")
        return self._hasher.hash(password, salt=salt)

    def verify(self, password: str | bytes, hash: str | bytes) -> bool:
        validate_str_or_bytes(password, "password")
        validate_str_or_bytes(hash, "hash")
        try:
            return self._hasher.verify(hash, password)
        except (
            argon2.exceptions.VerificationError,
            argon2.exceptions.InvalidHashError,
        ):
            return False

    def check_needs_rehash(self, hash: str | bytes) -> bool:
        validate_str_or_bytes(hash, "hash")
        return self._hasher.check_needs_rehash(ensure_str(hash))
