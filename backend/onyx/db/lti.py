from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import insert
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import LTI_CANVAS_COURSE_PROJECT_DESCRIPTION_PREFIX
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import HierarchyNodeType
from onyx.db.enums import IndexingStatus
from onyx.db.hierarchy import get_hierarchy_node_by_raw_id
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import HierarchyNodeByConnectorCredentialPair
from onyx.db.models import IndexAttempt
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
    token was revoked. `document_by_connector_credential_pair` and
    `hierarchy_node_by_connector_credential_pair` are keyed on
    (connector_id, credential_id), so their rows move with the cc-pair to keep
    document counts, hierarchy ownership and deletion bookkeeping intact.
    Does not commit.
    """
    old_credential_id = cc_pair.credential_id
    if old_credential_id == new_credential_id:
        return

    connector_id = cc_pair.connector_id

    # The hierarchy mapping has a non-deferrable composite foreign key to
    # connector_credential_pair, so neither side can be updated in place:
    # changing the child first points at a key that does not exist yet, and
    # changing the parent first orphans the child rows. Drop the mappings,
    # re-key the cc-pair, then recreate them under the new key.
    hierarchy_node_ids = list(
        db_session.scalars(
            select(HierarchyNodeByConnectorCredentialPair.hierarchy_node_id).where(
                HierarchyNodeByConnectorCredentialPair.connector_id == connector_id,
                HierarchyNodeByConnectorCredentialPair.credential_id
                == old_credential_id,
            )
        ).all()
    )
    db_session.execute(
        delete(HierarchyNodeByConnectorCredentialPair).where(
            HierarchyNodeByConnectorCredentialPair.connector_id == connector_id,
            HierarchyNodeByConnectorCredentialPair.credential_id == old_credential_id,
        )
    )

    db_session.execute(
        update(DocumentByConnectorCredentialPair)
        .where(
            DocumentByConnectorCredentialPair.connector_id == connector_id,
            DocumentByConnectorCredentialPair.credential_id == old_credential_id,
        )
        .values(credential_id=new_credential_id)
    )
    cc_pair.credential_id = new_credential_id
    db_session.flush()

    if hierarchy_node_ids:
        db_session.execute(
            insert(HierarchyNodeByConnectorCredentialPair),
            [
                {
                    "hierarchy_node_id": hierarchy_node_id,
                    "connector_id": connector_id,
                    "credential_id": new_credential_id,
                }
                for hierarchy_node_id in hierarchy_node_ids
            ],
        )
        db_session.flush()


def fetch_canvas_cc_pairs_for_credential(
    db_session: Session,
    credential_id: int,
) -> list[ConnectorCredentialPair]:
    """Return every Canvas cc-pair that authenticates with ``credential_id``.

    An instructor's Canvas OAuth credential is shared across all of their
    LTI courses, so revoking it affects each of these cc-pairs.
    """
    stmt = (
        select(ConnectorCredentialPair)
        .join(Connector)
        .where(
            Connector.source == DocumentSource.CANVAS,
            ConnectorCredentialPair.credential_id == credential_id,
        )
        .order_by(ConnectorCredentialPair.id.asc())
    )
    return list(db_session.scalars(stmt).unique().all())


def pause_cc_pairs_for_revoked_credential(
    db_session: Session,
    cc_pairs: list[ConnectorCredentialPair],
) -> None:
    """Stop indexing for cc-pairs whose credential is about to be revoked.

    Cancels any queued indexing attempts (including for a future search
    settings) and pauses each cc-pair so they don't fail their next sync with
    a token that no longer exists. Does not commit.
    """
    if not cc_pairs:
        return
    cc_pair_ids = [cc_pair.id for cc_pair in cc_pairs]
    db_session.execute(
        update(IndexAttempt)
        .where(IndexAttempt.connector_credential_pair_id.in_(cc_pair_ids))
        .where(IndexAttempt.status == IndexingStatus.NOT_STARTED)
        .values(
            status=IndexingStatus.CANCELED,
            error_msg="Canceled: Canvas connection was disconnected",
            time_started=datetime.now(timezone.utc),
        )
    )
    for cc_pair in cc_pairs:
        cc_pair.status = ConnectorCredentialPairStatus.PAUSED
    db_session.flush()
