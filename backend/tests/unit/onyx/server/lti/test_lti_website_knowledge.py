from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from sqlalchemy.dialects import postgresql

from onyx.configs.constants import DocumentSource
from onyx.db import lti_knowledge as knowledge
from onyx.db.document import get_lti_course_website_document_ids
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.hierarchy.models import DocumentSortDirection
from onyx.server.features.hierarchy.models import DocumentSortField
from onyx.server.lti import api
from onyx.server.lti import knowledge as lti_knowledge


def test_course_website_nodes_use_course_ownership_for_access() -> None:
    cc_pair = SimpleNamespace(connector_id=10, credential_id=20)
    with (
        patch.object(knowledge, "_course_cc_pairs", return_value=[cc_pair]),
        patch.object(knowledge, "_owned_hierarchy_node_ids", return_value={30}),
        patch.object(
            knowledge,
            "_accessible_hierarchy_node_ids",
            side_effect=AssertionError(
                "External permissions do not model course groups"
            ),
        ),
    ):
        scope = knowledge.get_lti_course_knowledge_scope(
            db_session=MagicMock(),
            course_id="course-1",
            source=DocumentSource.WEB,
            user_email="instructor@example.edu",
            external_group_ids=[],
        )

    assert scope.cc_pair_keys == [(10, 20)]
    assert scope.accessible_node_ids == {30}


def test_course_website_pages_use_course_owned_pairs() -> None:
    db_session = MagicMock()
    db_session.get.return_value = SimpleNamespace(source=DocumentSource.WEB)
    scope = knowledge.LtiCourseKnowledgeScope(
        cc_pair_keys=[(10, 20)], accessible_node_ids={30}
    )
    with (
        patch.object(knowledge, "get_lti_course_knowledge_scope", return_value=scope),
        patch.object(
            knowledge,
            "get_lti_course_website_documents_for_hierarchy_node_paginated",
            return_value=[],
        ) as fetch_website_pages,
        patch.object(
            knowledge,
            "get_accessible_documents_for_hierarchy_node_paginated",
            side_effect=AssertionError("Generic ACL excludes private course pages"),
        ),
    ):
        knowledge.get_lti_course_accessible_documents_for_hierarchy_node(
            db_session=db_session,
            course_id="course-1",
            parent_hierarchy_node_id=30,
            user_email="instructor@example.edu",
            external_group_ids=[],
            cursor=None,
            sort_field=DocumentSortField.NAME,
            sort_direction=DocumentSortDirection.ASC,
        )

    assert fetch_website_pages.call_args.kwargs["connector_credential_pairs"] == [
        (10, 20)
    ]
    assert fetch_website_pages.call_args.kwargs["parent_hierarchy_node_id"] == 30


def test_website_document_lookup_filters_node_and_connector_pair() -> None:
    db_session = MagicMock()
    db_session.execute.return_value.scalars.return_value.all.return_value = []

    get_lti_course_website_document_ids(
        db_session=db_session,
        document_ids=["page-1"],
        hierarchy_node_ids={30},
        connector_credential_pairs=[(10, 20)],
    )

    stmt = db_session.execute.call_args.args[0]
    query = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "page-1" in query
    assert "parent_hierarchy_node_id IN (30)" in query
    assert "(10, 20)" in query
    assert "DELETING" in query


@pytest.mark.parametrize("is_course_document", [True, False])
def test_course_website_document_selection_requires_course_ownership(
    is_course_document: bool,
) -> None:
    db_session = MagicMock()
    db_session.execute.return_value.scalars.return_value.all.return_value = []
    user = SimpleNamespace(email="instructor@example.edu")
    scope = knowledge.LtiCourseKnowledgeScope(
        cc_pair_keys=[(10, 20)], accessible_node_ids={30}
    )
    with (
        patch.object(lti_knowledge, "require_lti_instructor_launch_context"),
        patch.object(knowledge, "_all_lti_course_knowledge_scope", return_value=scope),
        patch.object(knowledge, "get_lti_course_knowledge_scope", return_value=scope),
        patch.object(knowledge, "get_user_external_group_ids", return_value=[]),
        patch.object(
            knowledge,
            "get_lti_course_website_document_ids",
            return_value={"page-1"} if is_course_document else set(),
        ),
    ):
        if is_course_document:
            lti_knowledge.validate_lti_course_knowledge_selection(
                db_session=db_session,
                course_id="course-1",
                user=user,  # type: ignore[arg-type]
                hierarchy_node_ids=[],
                document_ids=["page-1"],
            )
        else:
            with pytest.raises(OnyxError) as exc_info:
                lti_knowledge.validate_lti_course_knowledge_selection(
                    db_session=db_session,
                    course_id="course-1",
                    user=user,  # type: ignore[arg-type]
                    hierarchy_node_ids=[],
                    document_ids=["page-1"],
                )
            assert exc_info.value.error_code == OnyxErrorCode.UNAUTHORIZED


@pytest.mark.parametrize("belongs_to_course", [True, False])
def test_sync_website_requires_course_ownership(belongs_to_course: bool) -> None:
    db_session = MagicMock()
    user = MagicMock()
    cc_pair = SimpleNamespace(
        id=10 if belongs_to_course else 11,
        status=ConnectorCredentialPairStatus.ACTIVE,
    )
    with (
        patch.object(api, "_get_launch_context_for_course_or_raise") as launch,
        patch.object(api, "lti_roles_include_instructor", return_value=True),
        patch.object(api, "fetch_lti_course_website_cc_pairs", return_value=[cc_pair]),
        patch.object(api, "_trigger_cc_pair_reindex") as trigger,
    ):
        launch.return_value.roles = ["Instructor"]
        if belongs_to_course:
            api.sync_lti_course_website(
                course_id="course-1",
                cc_pair_id=10,
                user=user,
                db_session=db_session,
            )
            trigger.assert_called_once_with(10, db_session)
        else:
            with pytest.raises(OnyxError) as exc_info:
                api.sync_lti_course_website(
                    course_id="course-1",
                    cc_pair_id=10,
                    user=user,
                    db_session=db_session,
                )
            assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND
            trigger.assert_not_called()
