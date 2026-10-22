"""Exercise tutor saves against real course ownership and folder permissions."""

from collections.abc import Generator
from typing import NamedTuple
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import HierarchyNodeType
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import HierarchyNode
from onyx.db.models import HierarchyNodeByConnectorCredentialPair
from onyx.db.models import Persona
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.persona import api
from onyx.server.features.persona.models import PersonaUpsertRequest
from onyx.server.lti import knowledge
from onyx.server.settings.models import Settings
from onyx.tools.constants import SEARCH_TOOL_ID
from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import global_version
from tests.external_dependency_unit.conftest import create_test_user


class CourseTutor(NamedTuple):
    course_id: str
    owner: User
    tutor: Persona
    folders: dict[str, HierarchyNode]
    search_tool: Tool


@pytest.fixture
def course_tutor(db_session: Session) -> Generator[CourseTutor, None, None]:
    was_ee = global_version.is_ee_version()
    global_version.set_ee()
    fetch_versioned_implementation.cache_clear()
    course_id = f"tutor-knowledge-{uuid4().hex}"
    owner = create_test_user(db_session, "tutor-knowledge")
    credential = Credential(
        source=DocumentSource.GOOGLE_DRIVE,
        credential_json={},
        user_id=owner.id,
        is_lti_credential=True,
    )
    db_session.add(credential)
    db_session.flush()
    connectors = [
        Connector(
            name=f"Tutor knowledge {context_id}",
            source=DocumentSource.GOOGLE_DRIVE,
            input_type=InputType.LOAD_STATE,
            connector_specific_config={"lti_context_id": context_id},
        )
        for context_id in (course_id, f"{course_id}-other")
    ]
    db_session.add_all(connectors)
    db_session.flush()
    pairs = [
        ConnectorCredentialPair(
            connector_id=connector.id,
            credential_id=credential.id,
            name=connector.name,
            creator_id=owner.id,
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.PRIVATE,
        )
        for connector in connectors
    ]
    folders = {
        name: HierarchyNode(
            raw_node_id=f"{course_id}-{name}",
            display_name=name,
            source=DocumentSource.GOOGLE_DRIVE,
            node_type=HierarchyNodeType.FOLDER,
            is_public=name != "inaccessible",
        )
        for name in (
            "current",
            "new",
            "old-materials",
            "old-books",
            "other-course",
            "inaccessible",
            "unsaved-orphan",
        )
    }
    search_tool = Tool(name=f"Search {course_id}", in_code_tool_id=SEARCH_TOOL_ID)
    tutor = Persona(
        name=f"Tutor {course_id}",
        description="Original description",
        system_prompt="",
        task_prompt="",
        user_id=owner.id,
        tools=[search_tool],
        hierarchy_nodes=[
            folders["current"],
            folders["old-materials"],
            folders["old-books"],
        ],
    )
    db_session.add_all([*pairs, *folders.values(), tutor])
    db_session.flush()
    for name in ("current", "new", "inaccessible", "other-course"):
        pair = pairs[1] if name == "other-course" else pairs[0]
        db_session.add(
            HierarchyNodeByConnectorCredentialPair(
                hierarchy_node_id=folders[name].id,
                connector_id=pair.connector_id,
                credential_id=pair.credential_id,
            )
        )
    db_session.commit()
    search_tool_id = search_tool.id
    owner_id = owner.id
    credential_id = credential.id
    connector_ids = [connector.id for connector in connectors]
    folder_ids = [folder.id for folder in folders.values()]

    try:
        # Only the Redis launch context and settings store are replaced. Course
        # ownership, permissions, request validation, and persistence are real.
        with (
            patch.object(knowledge, "require_lti_instructor_launch_context"),
            patch.object(api, "load_settings", return_value=Settings()),
        ):
            yield CourseTutor(course_id, owner, tutor, folders, search_tool)
    finally:
        db_session.rollback()
        db_session.execute(delete(Persona).where(Persona.user_id == owner_id))
        db_session.execute(delete(Tool).where(Tool.id == search_tool_id))
        db_session.execute(
            delete(HierarchyNode).where(HierarchyNode.id.in_(folder_ids))
        )
        db_session.execute(
            delete(ConnectorCredentialPair).where(
                ConnectorCredentialPair.connector_id.in_(connector_ids)
            )
        )
        db_session.execute(delete(Connector).where(Connector.id.in_(connector_ids)))
        db_session.execute(delete(Credential).where(Credential.id == credential_id))
        db_session.execute(delete(User).where(User.__table__.c.id == owner_id))
        db_session.commit()
        if not was_ee:
            global_version.unset_ee()
        fetch_versioned_implementation.cache_clear()


def _request(
    course_tutor: CourseTutor, folder_names: list[str]
) -> PersonaUpsertRequest:
    return PersonaUpsertRequest(
        name=course_tutor.tutor.name,
        description="Updated description",
        document_set_ids=[],
        is_public=False,
        tool_ids=[course_tutor.search_tool.id],
        system_prompt="",
        task_prompt="",
        datetime_aware=True,
        lti_context_id=course_tutor.course_id,
        hierarchy_node_ids=[course_tutor.folders[name].id for name in folder_names],
    )


@pytest.mark.parametrize("remaining_folders", [["current", "new"], []])
def test_tutor_save_automatically_drops_saved_orphaned_folders(
    db_session: Session, course_tutor: CourseTutor, remaining_folders: list[str]
) -> None:
    request = _request(course_tutor, ["old-materials", "old-books", *remaining_folders])
    response = api.update_persona(
        persona_id=course_tutor.tutor.id,
        persona_upsert_request=request,
        user=course_tutor.owner,
        db_session=db_session,
    )

    expected_ids = {course_tutor.folders[name].id for name in remaining_folders}
    assert {node.id for node in response.hierarchy_nodes} == expected_ids
    expected_tool_ids = {course_tutor.search_tool.id} if remaining_folders else set()
    assert {tool.id for tool in response.tools} == expected_tool_ids
    db_session.expire_all()
    saved_tutor = db_session.get(Persona, course_tutor.tutor.id)
    assert saved_tutor is not None
    assert {node.id for node in saved_tutor.hierarchy_nodes} == expected_ids
    assert {tool.id for tool in saved_tutor.tools} == expected_tool_ids
    assert saved_tutor.description == "Updated description"


@pytest.mark.parametrize("remaining_folders", [["new"], []])
def test_tutor_save_preserves_explicit_deselections(
    db_session: Session, course_tutor: CourseTutor, remaining_folders: list[str]
) -> None:
    # No orphan IDs are submitted: empty knowledge must also disable Search
    # when the instructor deliberately clears the selection.
    response = api.update_persona(
        persona_id=course_tutor.tutor.id,
        persona_upsert_request=_request(course_tutor, remaining_folders),
        user=course_tutor.owner,
        db_session=db_session,
    )

    expected_ids = {course_tutor.folders[name].id for name in remaining_folders}
    expected_tool_ids = {course_tutor.search_tool.id} if remaining_folders else set()
    assert {node.id for node in response.hierarchy_nodes} == expected_ids
    assert {tool.id for tool in response.tools} == expected_tool_ids
    db_session.expire_all()
    saved_tutor = db_session.get(Persona, course_tutor.tutor.id)
    assert saved_tutor is not None
    assert {node.id for node in saved_tutor.hierarchy_nodes} == expected_ids
    assert {tool.id for tool in saved_tutor.tools} == expected_tool_ids


def test_tutor_search_can_be_reenabled_after_adding_knowledge(
    db_session: Session, course_tutor: CourseTutor
) -> None:
    api.update_persona(
        persona_id=course_tutor.tutor.id,
        persona_upsert_request=_request(course_tutor, []),
        user=course_tutor.owner,
        db_session=db_session,
    )
    response = api.update_persona(
        persona_id=course_tutor.tutor.id,
        persona_upsert_request=_request(course_tutor, ["new"]),
        user=course_tutor.owner,
        db_session=db_session,
    )
    assert {node.id for node in response.hierarchy_nodes} == {
        course_tutor.folders["new"].id
    }
    assert {tool.id for tool in response.tools} == {course_tutor.search_tool.id}


@pytest.mark.parametrize("is_lti_tutor", [True, False])
def test_empty_persona_creation_disables_search_only_for_lti(
    db_session: Session, course_tutor: CourseTutor, is_lti_tutor: bool
) -> None:
    request = _request(course_tutor, []).model_copy(
        update={
            "name": f"New {course_tutor.tutor.name}",
            "lti_context_id": course_tutor.course_id if is_lti_tutor else None,
        }
    )
    with patch.object(api, "mt_cloud_telemetry"):
        response = api.create_persona(
            persona_upsert_request=request,
            user=course_tutor.owner,
            db_session=db_session,
        )

    expected_tool_ids = set() if is_lti_tutor else {course_tutor.search_tool.id}
    assert not response.hierarchy_nodes
    assert {tool.id for tool in response.tools} == expected_tool_ids
    db_session.expire_all()
    saved_tutor = db_session.get(Persona, response.id)
    assert saved_tutor is not None
    assert {tool.id for tool in saved_tutor.tools} == expected_tool_ids


@pytest.mark.parametrize(
    "invalid_folder", ["other-course", "inaccessible", "unsaved-orphan"]
)
def test_tutor_save_still_rejects_invalid_folder_selections(
    db_session: Session, course_tutor: CourseTutor, invalid_folder: str
) -> None:
    # Owned folders remain invalid even when they were selected previously.
    if invalid_folder != "unsaved-orphan":
        course_tutor.tutor.hierarchy_nodes.append(course_tutor.folders[invalid_folder])
        db_session.commit()
    original_ids = {node.id for node in course_tutor.tutor.hierarchy_nodes}

    with pytest.raises(OnyxError) as exc_info:
        api.update_persona(
            persona_id=course_tutor.tutor.id,
            persona_upsert_request=_request(
                course_tutor, ["current", "old-materials", "old-books", invalid_folder]
            ),
            user=course_tutor.owner,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.UNAUTHORIZED
    db_session.expire_all()
    assert {node.id for node in course_tutor.tutor.hierarchy_nodes} == original_ids
    assert course_tutor.tutor.description == "Original description"
