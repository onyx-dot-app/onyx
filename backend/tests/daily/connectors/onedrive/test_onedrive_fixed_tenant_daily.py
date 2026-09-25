"""Live OneDrive coverage for the fixed, script-managed tenant corpus."""

import time
from collections.abc import Generator

import pytest

import onyx.connectors.onedrive.connector as onedrive_connector
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.microsoft_utils.graph_auth import MicrosoftAuthMethod
from onyx.connectors.models import Document, HierarchyNode
from onyx.connectors.onedrive.connector import (
    OneDriveConnector,
    drive_root_id,
    hierarchy_item_id,
)
from onyx.db.engine.sql_engine import SqlEngine
from tests.daily.connectors.utils import (
    ConnectorOutput,
    load_all_from_connector,
    to_sections,
    to_text_sections,
)
from tests.utils.onedrive_fixture import (
    ANONYMOUS_LINK_SKIP_REASON,
    FIXTURE_ROOT_NAME,
    AnonymousLinkOutcome,
    FilePath,
    FixtureState,
    FolderPath,
    OneDriveFixtureReader,
    build_fixture_reader,
    load_fixture_config,
)
from tests.utils.pytest_secrets import RedactedDict
from tests.utils.secret_names import TestSecret

pytestmark = [
    pytest.mark.usefixtures("enable_ee"),
    pytest.mark.secrets(
        TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID,
        TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID,
        TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY,
        TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD,
    ),
]

EXPECTED_BASELINE_FILES = {
    path
    for path in FilePath
    if path
    not in {
        FilePath.MOVE_DESTINATION,
        FilePath.EXCLUDED,
        FilePath.OVER_SIZE,
        FilePath.UNSUPPORTED,
    }
}
LIVE_PAGE_SIZE = 10


@pytest.fixture(scope="module", autouse=True)
def sql_engine() -> Generator[None, None, None]:
    try:
        SqlEngine.get_engine()
    except RuntimeError:
        with SqlEngine.scoped_engine(pool_size=2, max_overflow=1):
            yield
        return
    yield


@pytest.fixture(scope="module", autouse=True)
def live_page_size() -> Generator[None, None, None]:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            onedrive_connector, "DEFAULT_DRIVE_DELTA_PAGE_SIZE", LIVE_PAGE_SIZE
        )
        yield


@pytest.fixture(scope="module")
def onedrive_credentials(
    test_secrets: dict[TestSecret, str],
) -> RedactedDict[str, str]:
    return RedactedDict(
        {
            "authentication_method": MicrosoftAuthMethod.CERTIFICATE.value,
            "onedrive_client_id": test_secrets[
                TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID
            ],
            "onedrive_directory_id": test_secrets[
                TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID
            ],
            "onedrive_private_key": test_secrets[
                TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY
            ],
            "onedrive_certificate_password": test_secrets[
                TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD
            ],
        }
    )


@pytest.fixture(scope="module")
def fixture_reader() -> OneDriveFixtureReader:
    return build_fixture_reader(load_fixture_config())


@pytest.fixture(scope="module")
def baseline_state(fixture_reader: OneDriveFixtureReader) -> FixtureState:
    return fixture_reader.load_state()


def _connector(
    state: FixtureState,
    credentials: dict[str, str],
) -> OneDriveConnector:
    connector = OneDriveConnector(
        users=[
            state.owner.user_principal_name,
            state.second_owner.user_principal_name,
        ],
        excluded_paths=state.excluded_paths,
        treat_organization_link_as_public=True,
    )
    connector.load_credentials(credentials)
    return connector


def _load_corpus(
    state: FixtureState,
    credentials: dict[str, str],
    *,
    start: float = 0,
) -> ConnectorOutput:
    return load_all_from_connector(
        connector=_connector(state, credentials),
        start=start,
        end=time.time(),
        include_permissions=True,
    )


def _metadata_path(document: Document) -> str:
    path = document.metadata.get("path")
    assert isinstance(path, str)
    return path


def _document_text(document: Document) -> str:
    return "\n".join(to_text_sections(to_sections([document])))


def _documents_by_id(output: ConnectorOutput) -> dict[str, Document]:
    return {document.id: document for document in output.documents}


def _assert_access(
    document: Document,
    *,
    emails: set[str],
    group_ids: set[str] | None = None,
    is_public: bool = False,
) -> None:
    assert document.external_access == ExternalAccess(
        external_user_emails={email.lower() for email in emails},
        external_user_group_ids=group_ids or set(),
        is_public=is_public,
    )


def _assert_group_access(
    document: Document,
    *,
    owner_email: str,
    group_id: str,
    mail_nickname: str,
) -> None:
    access = document.external_access
    assert access is not None
    assert access.external_user_group_ids == {
        build_ext_group_name_for_onyx(group_id, DocumentSource.ONEDRIVE)
    }
    assert access.is_public is False
    owner_email = owner_email.lower()
    assert owner_email in access.external_user_emails
    group_emails = access.external_user_emails - {owner_email}
    assert len(group_emails) == 1
    assert {email.partition("@")[0] for email in group_emails} == {mail_nickname}


def _node_by_id(nodes: list[HierarchyNode], raw_node_id: str) -> HierarchyNode:
    matches = [node for node in nodes if node.raw_node_id == raw_node_id]
    assert matches
    return matches[-1]


def test_onedrive_fixed_corpus_indexing_identity_permissions_and_hierarchy(
    baseline_state: FixtureState,
    onedrive_credentials: dict[str, str],
) -> None:
    output = _load_corpus(baseline_state, onedrive_credentials)
    documents = output.documents
    documents_by_id = _documents_by_id(output)
    owner_email = baseline_state.owner.user_principal_name
    primary_email = baseline_state.primary_user.user_principal_name
    alternate_email = baseline_state.alternate_user.user_principal_name

    expected_ids = {
        baseline_state.files[path].id for path in EXPECTED_BASELINE_FILES
    } | {baseline_state.second_drive_duplicate.id}
    assert {document.id for document in documents} == expected_ids
    assert all(FIXTURE_ROOT_NAME in _metadata_path(document) for document in documents)
    assert all(
        "Onyx OneDrive fixture:" in _document_text(document) for document in documents
    )

    duplicate_documents = [
        document
        for document in documents
        if document.semantic_identifier == FilePath.IDENTITY.value.rsplit("/", 1)[-1]
    ]
    assert {document.id for document in duplicate_documents} == {
        baseline_state.files[FilePath.IDENTITY].id,
        baseline_state.second_drive_duplicate.id,
    }

    owner_only_paths = [
        FilePath.PRIVATE,
        FilePath.UPDATE,
        FilePath.DELETE,
        FilePath.IDENTITY,
    ]
    if (
        baseline_state.anonymous_link_outcome
        is AnonymousLinkOutcome.REJECTED_BY_TENANT_POLICY
    ):
        owner_only_paths.append(FilePath.ANONYMOUS_LINK)
    for path in owner_only_paths:
        _assert_access(
            documents_by_id[baseline_state.files[path].id],
            emails={owner_email},
        )
    _assert_access(
        documents_by_id[baseline_state.second_drive_duplicate.id],
        emails={baseline_state.second_owner.user_principal_name},
    )
    for path in (
        FilePath.DIRECT,
        FilePath.INHERITED,
        FilePath.INHERITED_NESTED,
        FilePath.MOVE,
        FilePath.REMOVE_SHARE,
    ):
        _assert_access(
            documents_by_id[baseline_state.files[path].id],
            emails={owner_email, primary_email},
        )
    for path in (FilePath.RESTRICTED, FilePath.RESTORE_INHERITANCE):
        _assert_access(
            documents_by_id[baseline_state.files[path].id],
            emails={owner_email, alternate_email},
        )
    _assert_group_access(
        documents_by_id[baseline_state.files[FilePath.VISIBLE_GROUP].id],
        owner_email=owner_email,
        group_id=baseline_state.visible_group.id,
        mail_nickname=baseline_state.visible_group.mail_nickname,
    )
    _assert_group_access(
        documents_by_id[baseline_state.files[FilePath.HIDDEN_GROUP].id],
        owner_email=owner_email,
        group_id=baseline_state.hidden_group.id,
        mail_nickname=baseline_state.hidden_group.mail_nickname,
    )
    public_paths = [FilePath.ORGANIZATION_LINK]
    if baseline_state.anonymous_link_outcome is AnonymousLinkOutcome.CREATED:
        public_paths.append(FilePath.ANONYMOUS_LINK)
    for path in public_paths:
        _assert_access(
            documents_by_id[baseline_state.files[path].id],
            emails={owner_email},
            is_public=True,
        )

    root = _node_by_id(output.hierarchy_nodes, drive_root_id(baseline_state.drive.id))
    fixture_root = _node_by_id(
        output.hierarchy_nodes,
        hierarchy_item_id(baseline_state.drive.id, baseline_state.root_item.id),
    )
    inherited = _node_by_id(
        output.hierarchy_nodes,
        hierarchy_item_id(
            baseline_state.drive.id,
            baseline_state.folders[FolderPath.INHERITED].id,
        ),
    )
    nested = _node_by_id(
        output.hierarchy_nodes,
        hierarchy_item_id(
            baseline_state.drive.id,
            baseline_state.folders[FolderPath.INHERITED_NESTED].id,
        ),
    )
    assert fixture_root.raw_parent_id == root.raw_node_id
    assert inherited.raw_parent_id == fixture_root.raw_node_id
    assert nested.raw_parent_id == inherited.raw_node_id


def test_onedrive_anonymous_link_when_tenant_policy_allows_it(
    baseline_state: FixtureState,
    onedrive_credentials: dict[str, str],
) -> None:
    if (
        baseline_state.anonymous_link_outcome
        is AnonymousLinkOutcome.REJECTED_BY_TENANT_POLICY
    ):
        pytest.skip(ANONYMOUS_LINK_SKIP_REASON)

    document = _documents_by_id(_load_corpus(baseline_state, onedrive_credentials))[
        baseline_state.files[FilePath.ANONYMOUS_LINK].id
    ]
    _assert_access(
        document,
        emails={baseline_state.owner.user_principal_name},
        is_public=True,
    )
