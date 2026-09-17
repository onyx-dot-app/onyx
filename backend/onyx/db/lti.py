from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.configs.constants import LTI_CANVAS_COURSE_PROJECT_DESCRIPTION_PREFIX
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import UserProject


def build_lti_course_project_description(course_id: str) -> str:
    return f"{LTI_CANVAS_COURSE_PROJECT_DESCRIPTION_PREFIX}{course_id}"


def get_lti_course_project_for_user(
    project_id: int,
    user_id: UUID,
    db_session: Session,
) -> UserProject | None:
    return (
        db_session.query(UserProject)
        .filter(
            UserProject.id == project_id,
            UserProject.user_id == user_id,
            UserProject.description.startswith(
                LTI_CANVAS_COURSE_PROJECT_DESCRIPTION_PREFIX
            ),
        )
        .one_or_none()
    )


def swap_lti_canvas_cc_pair_credential(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    new_credential_id: int,
) -> None:
    """Point an LTI course's Canvas cc-pair at a different instructor credential.

    Used when a co-instructor reconnects Canvas after the original instructor's
    token was revoked. `document_by_connector_credential_pair` is keyed on
    (connector_id, credential_id), so its rows move with the cc-pair to keep
    document counts and deletion bookkeeping intact. Does not commit.
    """
    old_credential_id = cc_pair.credential_id
    if old_credential_id == new_credential_id:
        return

    db_session.execute(
        update(DocumentByConnectorCredentialPair)
        .where(
            DocumentByConnectorCredentialPair.connector_id == cc_pair.connector_id,
            DocumentByConnectorCredentialPair.credential_id == old_credential_id,
        )
        .values(credential_id=new_credential_id)
    )
    cc_pair.credential_id = new_credential_id
    db_session.flush()
