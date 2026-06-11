"""Resolve a user's GitHub OAuth token from the built-in GitHub external app.

Shared by the sandbox proxy (to authenticate git over HTTPS) and any
api-server caller that needs the user's GitHub credential. Reads the same
``ExternalAppUserCredential`` the GitHub external app stores — there is no
separate token store.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.external_app import get_built_in_external_app
from onyx.db.external_app import get_external_app_user_credential


def get_user_github_access_token(db_session: Session, user_id: UUID) -> str | None:
    """The user's GitHub external-app OAuth token, or None if not connected."""
    app = get_built_in_external_app(db_session, ExternalAppType.GITHUB)
    if app is None:
        return None
    credential = get_external_app_user_credential(
        db_session, external_app_id=app.id, user_id=user_id
    )
    if credential is None:
        return None
    values = credential.user_credentials.get_value(apply_mask=False)
    token = values.get("access_token")
    return token if isinstance(token, str) and token else None
