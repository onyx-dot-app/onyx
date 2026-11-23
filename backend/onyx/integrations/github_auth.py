from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType
from onyx.db.external_app import get_built_in_external_app
from onyx.db.integration import get_integration_by_kind_row
from onyx.db.models import Integration
from onyx.db.users import fetch_user_by_id
from onyx.integrations.call_credentials import resolve_call_credentials
from onyx.integrations.connections import ConnectionProblem


def github_authorization_for(user_id: UUID, db_session: Session) -> str | None:
    """The Authorization header of the user's connection to the built-in GitHub
    integration, or None when the user has none that works."""
    github_app = get_built_in_external_app(db_session, ExternalAppType.GITHUB)
    if github_app is None:
        return None
    integration = get_integration_by_kind_row(
        Integration.external_app_id, github_app.id, db_session
    )
    user = fetch_user_by_id(db_session, user_id)
    if integration is None or not integration.enabled or user is None:
        return None
    credentials = resolve_call_credentials(integration, user, db_session)
    if isinstance(credentials, ConnectionProblem):
        return None
    return next(
        (
            value
            for name, value in credentials.headers.items()
            if name.lower() == "authorization"
        ),
        None,
    )
