import re
from functools import lru_cache

from pydantic import BaseModel
from pydantic import ConfigDict

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)


@lru_cache(maxsize=1024)
def _to_regex(glob: str) -> str:
    return ".*".join(re.escape(span) for span in glob.split("*"))


def _validate(glob: str) -> None:
    stripped = glob.strip()
    if not stripped:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "URL pattern must not be empty.")

    scheme = _SCHEME_RE.match(stripped)
    if scheme is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"URL pattern must start with http:// or https://: {glob!r}",
        )

    # The host (up to the first path separator) is the credential-injection
    # boundary, so it must be literal.
    host = stripped[scheme.end() :].split("/", 1)[0]
    if not host:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"URL pattern must include a host: {glob!r}"
        )
    if "*" in host:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"URL pattern host must be literal (no wildcards): {glob!r}",
        )


class UrlGlob(BaseModel):
    """A URL glob. Construct via ``parse`` at trust boundaries (it validates);
    the plain constructor trusts its input (used when rendering
    already-validated values loaded from the database)."""

    model_config = ConfigDict(frozen=True)

    value: str

    @classmethod
    def parse(cls, value: str) -> "UrlGlob":
        value = value.strip()
        _validate(value)
        return cls(value=value)

    def to_regex(self) -> str:
        """The anchored-by-``re.fullmatch`` regex this glob matches as."""
        return _to_regex(self.value)
