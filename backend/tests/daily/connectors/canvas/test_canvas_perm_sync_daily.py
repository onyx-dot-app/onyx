import time
from typing import cast
from unittest.mock import MagicMock

import pytest

from ee.onyx.connectors.perm_sync_valid import validate_canvas_perm_sync
from ee.onyx.external_permissions.canvas.access import build_course_permission_context
from ee.onyx.external_permissions.canvas.access import CanvasCoursePermissionContext
from ee.onyx.external_permissions.canvas.doc_sync import canvas_doc_sync
from ee.onyx.external_permissions.canvas.group_sync import canvas_group_sync
from onyx.access.models import DocExternalAccess
from onyx.access.models import ExternalAccess
from onyx.connectors.canvas.connector import canvas_all_users_group_id
from onyx.connectors.canvas.connector import canvas_course_group_id
from onyx.connectors.canvas.connector import canvas_group_group_id
from onyx.connectors.canvas.connector import canvas_section_group_id
from onyx.connectors.canvas.connector import CanvasAnnouncement
from onyx.connectors.canvas.connector import CanvasAssignment
from onyx.connectors.canvas.connector import CanvasConnector
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.db.models import ConnectorCredentialPair
from onyx.db.utils import DocumentRow
from onyx.db.utils import SortOrder
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

CANVAS_BASE_URL = "https://canvas.onyx.app"
COURSE_A_NAME = "intro to python"
COURSE_B_NAME = "introductory data structures"

TEACHER_EMAILS = {"justin@onyx.app", "admin-test@onyx.app", "test_user_3@onyx-test.com"}
STUDENT_1_EMAIL = "test_user_1@onyx-test.com"
STUDENT_2_EMAIL = "test_user_2@onyx-test.com"
COURSE_A_EMAILS = TEACHER_EMAILS | {STUDENT_1_EMAIL, STUDENT_2_EMAIL}

PAGE_A_TITLE = "home page"
ANN_ALL_TITLE = "A Ann All"
ANN_SEC1_TITLE = "A Ann Sec1"
ASG_EVERYONE_TITLE = "A Asg Everyone"
ASG_SEC1_TITLE = "A Asg Sec1"
ASG_STU2_TITLE = "A Asg Stu2"
ASG_GROUP_TITLE = "A Asg Group1"
PAGE_B_TITLE = "B Page"

MISSING_DOC_ID = "canvas-page-missing"

pytestmark = [
    pytest.mark.usefixtures("enable_ee"),
    pytest.mark.secrets(
        TestSecret.CANVAS_ADMIN_ACCESS_TOKEN,
        TestSecret.CANVAS_TEACHER_ACCESS_TOKEN,
        TestSecret.CANVAS_STUDENT_ACCESS_TOKEN,
    ),
]


def _build_connector(access_token: str) -> CanvasConnector:
    connector = CanvasConnector(canvas_base_url=CANVAS_BASE_URL)
    connector.load_credentials({"canvas_access_token": access_token})
    return connector


@pytest.fixture
def admin_connector(test_secrets: dict[TestSecret, str]) -> CanvasConnector:
    return _build_connector(test_secrets[TestSecret.CANVAS_ADMIN_ACCESS_TOKEN])


@pytest.fixture
def teacher_connector(test_secrets: dict[TestSecret, str]) -> CanvasConnector:
    return _build_connector(test_secrets[TestSecret.CANVAS_TEACHER_ACCESS_TOKEN])


@pytest.fixture
def student_connector(test_secrets: dict[TestSecret, str]) -> CanvasConnector:
    return _build_connector(test_secrets[TestSecret.CANVAS_STUDENT_ACCESS_TOKEN])


@pytest.fixture
def admin_cc_pair(test_secrets: dict[TestSecret, str]) -> ConnectorCredentialPair:
    return _mock_cc_pair(test_secrets[TestSecret.CANVAS_ADMIN_ACCESS_TOKEN])


@pytest.fixture
def teacher_cc_pair(test_secrets: dict[TestSecret, str]) -> ConnectorCredentialPair:
    return _mock_cc_pair(test_secrets[TestSecret.CANVAS_TEACHER_ACCESS_TOKEN])


def _course_id(connector: CanvasConnector, course_name: str) -> int:
    expected_name = course_name.casefold()
    for course in connector._list_courses():
        if course.name and course.name.casefold() == expected_name:
            return course.id
    raise AssertionError(f"Canvas course {course_name!r} not found")


def _course_id_or_none(connector: CanvasConnector, course_name: str) -> int | None:
    expected_name = course_name.casefold()
    for course in connector._list_courses():
        if course.name and course.name.casefold() == expected_name:
            return course.id
    return None


def _raw_course(connector: CanvasConnector, course_id: int) -> dict[str, object]:
    course, _ = connector.canvas_client.get(f"courses/{course_id}")
    assert isinstance(course, dict)
    return course


def _items_by_name(
    connector: CanvasConnector,
    course_id: int,
) -> dict[str, CanvasAnnouncement | CanvasAssignment]:
    items: dict[str, CanvasAnnouncement | CanvasAssignment] = {}
    items.update(
        {
            announcement.title: announcement
            for announcement in connector._list_announcements(course_id)
        }
    )
    items.update(
        {
            assignment.name: assignment
            for assignment in connector._list_assignments(course_id)
        }
    )
    return items


def _section_id_from_announcement(
    connector: CanvasConnector,
    course_id: int,
    title: str,
) -> int:
    announcement = _items_by_name(connector, course_id)[title]
    assert isinstance(announcement, CanvasAnnouncement)
    assert announcement.sections
    return announcement.sections[0].id


def _canvas_group_id_from_assignment(
    connector: CanvasConnector,
    course_id: int,
    title: str,
) -> int:
    assignment = _items_by_name(connector, course_id)[title]
    assert isinstance(assignment, CanvasAssignment)
    group_ids = [
        override.group_id
        for override in assignment.overrides
        if override.group_id is not None
    ]
    assert group_ids
    return group_ids[0]


def _section_ids_from_assignment(
    connector: CanvasConnector,
    course_id: int,
    title: str,
) -> set[int]:
    assignment = _items_by_name(connector, course_id)[title]
    assert isinstance(assignment, CanvasAssignment)
    return {
        override.course_section_id
        for override in assignment.overrides
        if override.course_section_id is not None
    }


def _context(
    connector: CanvasConnector, course_id: int
) -> CanvasCoursePermissionContext:
    return build_course_permission_context(connector.canvas_client, course_id)


def _expected_course_a_access(
    connector: CanvasConnector,
    course_id: int,
) -> dict[str, ExternalAccess]:
    context = _context(connector, course_id)
    ann_sec1_section_ids = {
        _section_id_from_announcement(connector, course_id, ANN_SEC1_TITLE)
    }
    asg_sec1_section_ids = _section_ids_from_assignment(
        connector,
        course_id,
        ASG_SEC1_TITLE,
    )
    group_x_id = _canvas_group_id_from_assignment(connector, course_id, ASG_GROUP_TITLE)
    course_group = {canvas_course_group_id(course_id)}
    canvas_group = {canvas_group_group_id(group_x_id)}

    return {
        PAGE_A_TITLE: ExternalAccess(set(), course_group, False),
        ANN_ALL_TITLE: ExternalAccess(set(), course_group, False),
        ANN_SEC1_TITLE: ExternalAccess(
            context.staff_emails,
            {
                canvas_section_group_id(section_id)
                for section_id in ann_sec1_section_ids
            },
            False,
        ),
        ASG_EVERYONE_TITLE: ExternalAccess(set(), course_group, False),
        ASG_SEC1_TITLE: ExternalAccess(
            context.staff_emails,
            {
                canvas_section_group_id(section_id)
                for section_id in asg_sec1_section_ids
            },
            False,
        ),
        ASG_STU2_TITLE: ExternalAccess(
            context.staff_emails | {STUDENT_2_EMAIL},
            set(),
            False,
        ),
        ASG_GROUP_TITLE: ExternalAccess(context.staff_emails, canvas_group, False),
    }


def _fixture_doc_access(
    connector: CanvasConnector,
    course_id: int,
) -> dict[str, ExternalAccess]:
    docs = load_all_from_connector(
        connector=connector,
        start=0.0,
        end=time.time(),
        include_permissions=True,
    ).documents
    access_by_name: dict[str, ExternalAccess] = {}
    for doc in docs:
        if doc.metadata.get("course_id") != str(course_id):
            continue
        assert doc.external_access is not None
        access_by_name[doc.semantic_identifier] = doc.external_access
    return access_by_name


def _collect_slim_docs(
    connector: CanvasConnector,
) -> dict[str, SlimDocument]:
    slim_docs: dict[str, SlimDocument] = {}
    for batch in connector.retrieve_all_slim_docs_perm_sync(start=0, end=time.time()):
        for item in batch:
            if isinstance(item, HierarchyNode):
                continue
            slim_docs[item.id] = item
    return slim_docs


def _mock_cc_pair(access_token: str) -> ConnectorCredentialPair:
    cc_pair = MagicMock(spec=ConnectorCredentialPair)
    cc_pair.id = 1
    cc_pair.connector = MagicMock()
    cc_pair.connector.connector_specific_config = {
        "canvas_base_url": CANVAS_BASE_URL,
    }
    cc_pair.connector.indexing_start = None
    cc_pair.credential = MagicMock()
    cc_pair.credential.credential_json = MagicMock()
    cc_pair.credential.credential_json.get_value.return_value = {
        "canvas_access_token": access_token,
    }
    return cast(ConnectorCredentialPair, cc_pair)


def _empty_existing_docs(
    sort_order: SortOrder | None = None,  # noqa: ARG001
) -> list[DocumentRow]:
    return []


def test_canvas_indexing_path_has_expected_access(
    teacher_connector: CanvasConnector,
) -> None:
    course_id = _course_id(teacher_connector, COURSE_A_NAME)
    expected_access = _expected_course_a_access(teacher_connector, course_id)
    doc_access = _fixture_doc_access(teacher_connector, course_id)

    for title, expected in expected_access.items():
        assert doc_access[title] == expected, title


def test_canvas_slim_docs_match_indexing_access(
    teacher_connector: CanvasConnector,
) -> None:
    course_id = _course_id(teacher_connector, COURSE_A_NAME)
    docs = load_all_from_connector(
        connector=teacher_connector,
        start=0.0,
        end=time.time(),
        include_permissions=True,
    ).documents
    slim_docs = _collect_slim_docs(teacher_connector)
    fixture_docs = [
        doc for doc in docs if doc.metadata.get("course_id") == str(course_id)
    ]

    assert {doc.id for doc in fixture_docs}.issubset(slim_docs)
    for doc in fixture_docs:
        assert slim_docs[doc.id].external_access == doc.external_access


def test_canvas_doc_sync_emits_access_and_removes_missing_docs(
    teacher_cc_pair: ConnectorCredentialPair,
    teacher_connector: CanvasConnector,
) -> None:
    course_id = _course_id(teacher_connector, COURSE_A_NAME)
    indexed_access = _fixture_doc_access(teacher_connector, course_id)

    def fetch_existing_doc_ids() -> list[str]:
        return [MISSING_DOC_ID]

    doc_access = list(
        canvas_doc_sync(
            teacher_cc_pair,
            _empty_existing_docs,
            fetch_existing_doc_ids,
            None,
        )
    )
    by_doc_id = {
        access.doc_id: access
        for access in doc_access
        if isinstance(access, DocExternalAccess)
    }
    docs = load_all_from_connector(
        connector=teacher_connector,
        start=0.0,
        end=time.time(),
        include_permissions=True,
    ).documents

    for doc in docs:
        if doc.metadata.get("course_id") != str(course_id):
            continue
        if doc.semantic_identifier not in indexed_access:
            continue
        assert (
            by_doc_id[doc.id].external_access == indexed_access[doc.semantic_identifier]
        )

    assert by_doc_id[MISSING_DOC_ID].external_access == ExternalAccess.empty()


def test_canvas_group_sync_emits_expected_groups(
    teacher_cc_pair: ConnectorCredentialPair,
    teacher_connector: CanvasConnector,
) -> None:
    course_a_id = _course_id(teacher_connector, COURSE_A_NAME)
    section_a1_id = _section_id_from_announcement(
        teacher_connector,
        course_a_id,
        ANN_SEC1_TITLE,
    )
    group_x_id = _canvas_group_id_from_assignment(
        teacher_connector,
        course_a_id,
        ASG_GROUP_TITLE,
    )
    groups = {
        group.id: set(group.user_emails)
        for group in canvas_group_sync("t", teacher_cc_pair)
    }
    context = _context(teacher_connector, course_a_id)

    assert groups[canvas_course_group_id(course_a_id)] == set(
        context.user_id_to_email.values()
    )
    assert canvas_section_group_id(section_a1_id) in groups
    assert groups[canvas_group_group_id(group_x_id)] == {STUDENT_1_EMAIL}
    if context.is_public:
        assert set(context.user_id_to_email.values()).issubset(
            groups[canvas_all_users_group_id()]
        )


def test_canvas_public_course_admin_uses_all_users_group(
    admin_connector: CanvasConnector,
) -> None:
    course_id = _course_id(admin_connector, COURSE_B_NAME)
    access = _fixture_doc_access(admin_connector, course_id)[PAGE_B_TITLE]

    assert access == ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids={
            canvas_course_group_id(course_id),
            canvas_all_users_group_id(),
        },
        is_public=False,
    )


def test_canvas_public_course_teacher_uses_all_users_group(
    teacher_connector: CanvasConnector,
) -> None:
    course_id = _course_id_or_none(teacher_connector, COURSE_B_NAME)
    if course_id is None:
        pytest.skip("Teacher token cannot see the Course B public-course fixture")

    raw_course = _raw_course(teacher_connector, course_id)
    if not (raw_course.get("is_public") or raw_course.get("is_public_to_auth_users")):
        pytest.skip("Course B is not currently public in the live Canvas fixture")

    access = _fixture_doc_access(teacher_connector, course_id)[PAGE_B_TITLE]

    assert access == ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids={
            canvas_course_group_id(course_id),
            canvas_all_users_group_id(),
        },
        is_public=False,
    )


def test_canvas_perm_sync_validation(
    admin_connector: CanvasConnector,
    teacher_connector: CanvasConnector,
    student_connector: CanvasConnector,
) -> None:
    validate_canvas_perm_sync(admin_connector)
    validate_canvas_perm_sync(teacher_connector)

    with pytest.raises(InsufficientPermissionsError):
        validate_canvas_perm_sync(student_connector)
