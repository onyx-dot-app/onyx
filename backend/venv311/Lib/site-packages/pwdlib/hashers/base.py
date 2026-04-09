import typing


def validate_str_or_bytes(value: typing.Any, param_name: str) -> None:
    """
    Validate that a value is a string or bytes.

    Args:
        value: The value to validate.
        param_name: The name of the parameter being validated.

    Raises:
        TypeError: If the value is not a string or bytes.
    """
    if not isinstance(value, (str, bytes)):
        raise TypeError(f"{param_name} must be str or bytes")  # noqa: TRY003


def ensure_str(v: str | bytes, *, encoding: str = "utf-8") -> str:
    return v.decode(encoding) if isinstance(v, bytes) else v


def ensure_bytes(v: str | bytes, *, encoding: str = "utf-8") -> bytes:
    return v.encode(encoding) if isinstance(v, str) else v


class HasherProtocol(typing.Protocol):
    @classmethod
    def identify(cls, hash: str | bytes) -> bool: ...

    def hash(self, password: str | bytes, *, salt: bytes | None = None) -> str: ...

    def verify(self, password: str | bytes, hash: str | bytes) -> bool: ...

    def check_needs_rehash(self, hash: str | bytes) -> bool: ...


__all__ = ["HasherProtocol", "ensure_str", "validate_str_or_bytes"]
