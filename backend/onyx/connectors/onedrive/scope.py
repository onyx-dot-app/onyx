from pydantic import EmailStr, TypeAdapter, ValidationError

from onyx.connectors.exceptions import ConnectorValidationError

_EMAIL_ADAPTER = TypeAdapter(EmailStr)


def normalized_user_email(entry: str) -> str | None:
    """A Users entry as the email indexing reads, or None when it is not an
    email. The caller skips blank entries."""
    try:
        return str(_EMAIL_ADAPTER.validate_python(entry.strip())).casefold()
    except ValidationError:
        return None


def normalize_configured_users(users: list[str] | None) -> list[str]:
    raw_users = users or []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_user in raw_users:
        candidate = raw_user.strip()
        if not candidate:
            continue
        user = normalized_user_email(candidate)
        if user is None:
            raise ConnectorValidationError(
                f"Invalid OneDrive user email: {candidate!r}."
            )
        if user in seen:
            continue
        seen.add(user)
        normalized.append(user)
    if raw_users and not normalized:
        raise ConnectorValidationError(
            "OneDrive user entries must include at least one email."
        )
    return normalized
