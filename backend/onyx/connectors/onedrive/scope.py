from pydantic import EmailStr, TypeAdapter, ValidationError

from onyx.connectors.exceptions import ConnectorValidationError

_EMAIL_ADAPTER = TypeAdapter(EmailStr)


def normalize_configured_users(users: list[str] | None) -> list[str]:
    raw_users = users or []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_user in raw_users:
        candidate = raw_user.strip()
        if not candidate:
            continue
        try:
            user = str(_EMAIL_ADAPTER.validate_python(candidate)).casefold()
        except ValidationError as error:
            raise ConnectorValidationError(
                f"Invalid OneDrive user email: {candidate!r}."
            ) from error
        if user in seen:
            continue
        seen.add(user)
        normalized.append(user)
    if raw_users and not normalized:
        raise ConnectorValidationError(
            "OneDrive user entries must include at least one email."
        )
    return normalized
