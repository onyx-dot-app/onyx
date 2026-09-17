from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import LTI_CANVAS_COURSE_PROJECT_DESCRIPTION_PREFIX
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import get_hierarchy_node_by_raw_id
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


def fetch_canvas_course_node_id_for_cc_pair(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> int | None:
    """Resolve the indexed COURSE ``HierarchyNode`` for an LTI course's Canvas
    cc-pair.

    The Canvas connector emits each course as a COURSE node whose raw id is
    ``canvas-course-<canvas course id>``, and the LTI setup flow configures
    the connector with exactly that course id. Looking the node up by raw id
    is exact (unlike matching on the course title, which breaks on duplicate
    names). Returns None until the connector has indexed the course node.
    """
    connector = cc_pair.connector
    if connector is None:
        return None
    course_ids = (connector.connector_specific_config or {}).get("course_ids")
    if course_ids is None:
        return None
    candidates = course_ids if isinstance(course_ids, list) else [course_ids]
    if len(candidates) != 1:
        return None

    node = get_hierarchy_node_by_raw_id(
        db_session=db_session,
        raw_node_id=f"canvas-course-{candidates[0]}",
        source=DocumentSource.CANVAS,
    )
    if node is None or node.node_type != HierarchyNodeType.COURSE:
        return None
    return node.id


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
