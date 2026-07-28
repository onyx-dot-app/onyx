from datetime import datetime, timezone
from typing import cast
from unittest.mock import MagicMock

import pytest
from box_sdk_gen import BoxCCGAuth, BoxClient
from box_sdk_gen.schemas.file_full import FileFull
from box_sdk_gen.schemas.folder_full import FolderFull
from box_sdk_gen.schemas.folder_mini import FolderMini
from box_sdk_gen.schemas.items import Items
from box_sdk_gen.schemas.user_mini import UserMini
from box_sdk_gen.schemas.web_link import (
    WebLink,
    WebLinkSharedLinkEffectiveAccessField,
    WebLinkSharedLinkEffectivePermissionField,
    WebLinkSharedLinkField,
)

from onyx.access.models import ExternalAccess
from onyx.connectors.box.connector import BoxConnector, parse_box_folder_id
from onyx.connectors.box.models import BoxFolderFrontierEntry
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    TextSection,
)
from tests.unit.onyx.connectors.box.fake_box_client import (
    FakeBoxClient,
    make_box_api_error,
)

_OWNER = UserMini(id="u1", name="Alice", login="alice@example.com")

_START = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
_END = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()


def _file(
    file_id: str,
    name: str,
    modified: datetime,
    size: int = 10,
    created: datetime | None = None,
) -> FileFull:
    return FileFull(
        id=file_id,
        name=name,
        size=size,
        modified_at=modified,
        created_at=created or modified,
        owned_by=_OWNER,
    )


def _build_fake_client(
    fail_listing_folder_ids: set[str] | None = None,
) -> FakeBoxClient:
    """Tree:

    Root (100)
    ├── a.txt (1, 2024-06-01)   [page 1 of Root's listing]
    ├── old.txt (2, 2020-01-01) [page 2, outside poll window]
    ├── Sub (200)               [page 2]
    │   ├── b.txt (3, 2024-06-02)
    │   └── web link (9, 2024-06-03)
    """
    return FakeBoxClient(
        folders_by_id={
            "100": FolderFull(id="100", name="Root"),
            "200": FolderFull(id="200", name="Sub"),
        },
        pages={
            ("100", None): Items(
                entries=[
                    _file(
                        "1",
                        "a.txt",
                        datetime(2024, 6, 1, tzinfo=timezone.utc),
                        created=datetime(2024, 5, 1, tzinfo=timezone.utc),
                    )
                ],
                next_marker="marker-1",
            ),
            ("100", "marker-1"): Items(
                entries=[
                    _file("2", "old.txt", datetime(2020, 1, 1, tzinfo=timezone.utc)),
                    FolderMini(id="200", name="Sub"),
                ],
                next_marker=None,
            ),
            ("200", None): Items(
                entries=[
                    _file("3", "b.txt", datetime(2024, 6, 2, tzinfo=timezone.utc)),
                    WebLink(
                        id="9",
                        url="https://example.com",
                        name="Example Link",
                        description="an example",
                        modified_at=datetime(2024, 6, 3, tzinfo=timezone.utc),
                    ),
                ],
                next_marker=None,
            ),
        },
        file_contents={
            "1": b"alpha content",
            "2": b"old content",
            "3": b"bravo content",
        },
        fail_listing_folder_ids=fail_listing_folder_ids,
    )


def _make_connector(
    fake_client: FakeBoxClient,
    include_web_links: bool = False,
    folder_ids: list[str] | None = None,
) -> BoxConnector:
    connector = BoxConnector(
        folder_ids=folder_ids or ["100"], include_web_links=include_web_links
    )
    connector._content_client = cast(BoxClient, fake_client)
    connector._enterprise_client = cast(BoxClient, fake_client)
    return connector


def _run_to_completion(
    connector: BoxConnector,
    start: float = _START,
    end: float = _END,
) -> list[Document | HierarchyNode | ConnectorFailure]:
    """Drives the connector exactly the way the runner does, JSON round-tripping
    the checkpoint at every boundary to pin serializability and resumability."""
    checkpoint = connector.build_dummy_checkpoint()
    outputs: list[Document | HierarchyNode | ConnectorFailure] = []
    iterations = 0
    while checkpoint.has_more:
        iterations += 1
        assert iterations < 100, "traversal did not terminate"
        generator = connector.load_from_checkpoint(start, end, checkpoint)
        while True:
            try:
                outputs.append(next(generator))
            except StopIteration as e:
                checkpoint = connector.validate_checkpoint_json(
                    e.value.model_dump_json()
                )
                break
    return outputs


def test_full_traversal_documents_and_hierarchy() -> None:
    fake_client = _build_fake_client()
    connector = _make_connector(fake_client)
    outputs = _run_to_completion(connector)

    documents = [o for o in outputs if isinstance(o, Document)]
    nodes = [o for o in outputs if isinstance(o, HierarchyNode)]
    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]

    assert not failures
    assert {d.id for d in documents} == {"box-file-1", "box-file-3"}
    assert {n.raw_node_id for n in nodes} == {"100", "200"}

    by_id = {d.id: d for d in documents}
    doc_a = by_id["box-file-1"]
    assert doc_a.semantic_identifier == "a.txt"
    assert doc_a.metadata == {"path": "Root"}
    assert doc_a.parent_hierarchy_raw_node_id == "100"
    assert doc_a.doc_updated_at is not None
    assert doc_a.doc_updated_at == datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert doc_a.doc_updated_at.tzinfo == timezone.utc
    # created_at is distinct from modified_at, proving it maps to file.created_at
    assert doc_a.doc_created_at is not None
    assert doc_a.doc_created_at == datetime(2024, 5, 1, tzinfo=timezone.utc)
    assert doc_a.doc_created_at.tzinfo == timezone.utc
    assert doc_a.primary_owners is not None
    assert doc_a.primary_owners[0].email == "alice@example.com"
    section = doc_a.sections[0]
    assert isinstance(section, TextSection)
    assert section.link == "https://app.box.com/file/1"
    assert section.text == "alpha content"

    doc_b = by_id["box-file-3"]
    assert doc_b.metadata == {"path": "Root/Sub"}
    assert doc_b.parent_hierarchy_raw_node_id == "200"

    root_node = next(n for n in nodes if n.raw_node_id == "100")
    sub_node = next(n for n in nodes if n.raw_node_id == "200")
    assert root_node.raw_parent_id is None
    assert root_node.display_name == "Root"
    assert sub_node.raw_parent_id == "100"


def test_poll_window_excludes_out_of_range_files() -> None:
    fake_client = _build_fake_client()
    connector = _make_connector(fake_client)
    outputs = _run_to_completion(connector)
    document_ids = {o.id for o in outputs if isinstance(o, Document)}
    # old.txt (2020) is outside [2023, 2025)
    assert "box-file-2" not in document_ids

    # a wide-open window picks it up
    connector_all = _make_connector(_build_fake_client())
    outputs_all = _run_to_completion(connector_all, start=0, end=_END)
    document_ids_all = {o.id for o in outputs_all if isinstance(o, Document)}
    assert "box-file-2" in document_ids_all


def test_parents_yielded_before_children() -> None:
    fake_client = _build_fake_client()
    connector = _make_connector(fake_client)
    outputs = _run_to_completion(connector)

    seen_node_ids: set[str] = set()
    for output in outputs:
        if isinstance(output, HierarchyNode):
            if output.raw_parent_id is not None:
                assert output.raw_parent_id in seen_node_ids
            seen_node_ids.add(output.raw_node_id)
        elif isinstance(output, Document):
            assert output.parent_hierarchy_raw_node_id in seen_node_ids


def test_pagination_marker_round_trips_through_checkpoint() -> None:
    fake_client = _build_fake_client()
    connector = _make_connector(fake_client)
    _run_to_completion(connector)

    root_calls = [
        marker
        for folder_id, marker in fake_client.folders.listing_calls
        if folder_id == "100"
    ]
    assert root_calls == [None, "marker-1"]


def test_folder_listing_failure_is_isolated() -> None:
    fake_client = _build_fake_client(fail_listing_folder_ids={"200"})
    connector = _make_connector(fake_client)
    outputs = _run_to_completion(connector)

    documents = [o for o in outputs if isinstance(o, Document)]
    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]

    # Root's file still indexed; the broken subtree surfaces as a failure.
    assert {d.id for d in documents} == {"box-file-1"}
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == "200"


def test_web_links_indexed_only_when_enabled() -> None:
    connector_without = _make_connector(_build_fake_client())
    ids_without = {
        o.id for o in _run_to_completion(connector_without) if isinstance(o, Document)
    }
    assert "box-weblink-9" not in ids_without

    connector_with = _make_connector(_build_fake_client(), include_web_links=True)
    outputs = _run_to_completion(connector_with)
    web_link_doc = next(
        o for o in outputs if isinstance(o, Document) and o.id == "box-weblink-9"
    )
    assert web_link_doc.semantic_identifier == "Example Link"
    section = web_link_doc.sections[0]
    assert isinstance(section, TextSection)
    assert section.link == "https://example.com"
    assert "an example" in (section.text or "")


def test_slim_retrieval_matches_full_retrieval_ids() -> None:
    connector = _make_connector(_build_fake_client(), include_web_links=True)
    slim_ids: set[str] = set()
    for batch in connector.retrieve_all_slim_docs(start=_START, end=_END):
        for item in batch:
            if isinstance(item, HierarchyNode):
                continue
            slim_ids.add(item.id)

    full_connector = _make_connector(_build_fake_client(), include_web_links=True)
    full_ids = {
        o.id for o in _run_to_completion(full_connector) if isinstance(o, Document)
    }
    assert slim_ids == full_ids


def test_slim_retrieval_raises_on_subtree_failure() -> None:
    connector = _make_connector(_build_fake_client(fail_listing_folder_ids={"200"}))
    with pytest.raises(RuntimeError, match="slim retrieval failed"):
        for _ in connector.retrieve_all_slim_docs(start=_START, end=_END):
            pass


def test_unsupported_and_oversized_files_are_skipped() -> None:
    fake_client = FakeBoxClient(
        folders_by_id={"100": FolderFull(id="100", name="Root")},
        pages={
            ("100", None): Items(
                entries=[
                    _file("1", "ok.txt", datetime(2024, 6, 1, tzinfo=timezone.utc)),
                    _file("2", "binary.exe", datetime(2024, 6, 1, tzinfo=timezone.utc)),
                    _file(
                        "3",
                        "huge.txt",
                        datetime(2024, 6, 1, tzinfo=timezone.utc),
                        size=10**12,
                    ),
                    # image skipped because allow_images defaults to False
                    _file("4", "pic.png", datetime(2024, 6, 1, tzinfo=timezone.utc)),
                ],
                next_marker=None,
            ),
        },
        file_contents={"1": b"fine"},
    )
    connector = _make_connector(fake_client)
    outputs = _run_to_completion(connector)
    documents = [o for o in outputs if isinstance(o, Document)]
    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert {d.id for d in documents} == {"box-file-1"}
    assert not failures


def test_download_stops_when_stream_exceeds_size_threshold() -> None:
    fake_client = FakeBoxClient(
        folders_by_id={"100": FolderFull(id="100", name="Root")},
        pages={
            ("100", None): Items(
                entries=[
                    _file(
                        "1",
                        "underreported.txt",
                        datetime(2024, 6, 1, tzinfo=timezone.utc),
                        size=1,
                    )
                ],
                next_marker=None,
            )
        },
        file_contents={"1": b"content larger than metadata"},
    )
    connector = _make_connector(fake_client)
    connector.size_threshold = 4

    outputs = _run_to_completion(connector)

    assert not [output for output in outputs if isinstance(output, Document)]


def _mixed_indexability_client() -> FakeBoxClient:
    return FakeBoxClient(
        folders_by_id={"100": FolderFull(id="100", name="Root")},
        pages={
            ("100", None): Items(
                entries=[
                    _file("1", "ok.txt", datetime(2024, 6, 1, tzinfo=timezone.utc)),
                    _file("2", "binary.exe", datetime(2024, 6, 1, tzinfo=timezone.utc)),
                    _file(
                        "3",
                        "huge.txt",
                        datetime(2024, 6, 1, tzinfo=timezone.utc),
                        size=10**12,
                    ),
                    _file("4", "pic.png", datetime(2024, 6, 1, tzinfo=timezone.utc)),
                ],
                next_marker=None,
            ),
        },
        file_contents={"1": b"fine"},
    )


def test_slim_retrieval_skips_non_indexable_files() -> None:
    """The slim/pruning enumeration must apply the same size/type gate as the
    full path, else pruning would keep documents alive for files that can never
    be indexed."""
    connector = _make_connector(_mixed_indexability_client())
    slim_ids: set[str] = set()
    for batch in connector.retrieve_all_slim_docs(start=_START, end=_END):
        for item in batch:
            if isinstance(item, HierarchyNode):
                continue
            slim_ids.add(item.id)
    assert slim_ids == {"box-file-1"}


def test_perm_sync_skips_root_folder_collaborations() -> None:
    """A whole-enterprise connector seeds at root folder 0, which Box refuses to
    return collaborations for (HTTP 400). Perm sync must skip that call rather
    than fail the whole run."""
    modified = datetime(2024, 6, 1, tzinfo=timezone.utc)
    fake_client = FakeBoxClient(
        folders_by_id={"0": FolderFull(id="0", name="All Files", owned_by=_OWNER)},
        pages={
            ("0", None): Items(
                entries=[_file("1", "a.txt", modified)], next_marker=None
            )
        },
        file_contents={"1": b"hi"},
    )
    connector = BoxConnector()  # no folder_ids -> whole-enterprise (root "0")
    connector._content_client = cast(BoxClient, fake_client)
    connector._enterprise_client = cast(BoxClient, fake_client)
    connector._enterprise_id = "ent"

    slim_ids: set[str] = set()
    for batch in connector.retrieve_all_slim_docs_perm_sync(start=_START, end=_END):
        for item in batch:
            if isinstance(item, HierarchyNode):
                continue
            slim_ids.add(item.id)

    assert slim_ids == {"box-file-1"}
    # root folder collaborations were never queried (Box would 400)
    assert "0" not in fake_client.list_collaborations.folder_collaboration_calls


@pytest.mark.usefixtures("enable_ee")
def test_web_link_shared_link_access_consistent_full_vs_slim() -> None:
    """The slim (perm-sync) path must apply a web link's own shared link the same
    as the full path; otherwise perm sync overwrites and revokes the link-granted
    (public/company) access."""
    connector = _make_connector(_build_fake_client(), include_web_links=True)
    connector._enterprise_id = "ent"
    web_link = WebLink(
        id="9",
        url="https://example.com",
        name="Example",
        modified_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        shared_link=WebLinkSharedLinkField(
            url="https://app.box.com/s/abc",
            effective_access=WebLinkSharedLinkEffectiveAccessField.OPEN,
            effective_permission=WebLinkSharedLinkEffectivePermissionField.CAN_PREVIEW,
            is_password_enabled=False,
            download_count=0,
            preview_count=0,
        ),
    )
    folder = BoxFolderFrontierEntry(
        folder_id="100",
        display_name="Root",
        parent_folder_id=None,
        path="Root",
        access=ExternalAccess.empty(),
    )

    full = connector._convert_web_link(web_link, folder, include_permissions=True)
    slim = connector._build_slim_document(web_link, folder, include_permissions=True)

    assert full is not None and full.external_access is not None
    assert slim.external_access is not None
    # the open shared link makes the bookmark public in BOTH paths
    assert full.external_access.is_public is True
    assert full.external_access == slim.external_access


@pytest.mark.parametrize(
    "value,expected",
    [
        ("123456789", "123456789"),
        ("  123456789 ", "123456789"),
        ("https://app.box.com/folder/123456789", "123456789"),
        ("https://acme.app.box.com/folder/123456789", "123456789"),
        # Box uses both singular and plural folder path segments
        ("https://app.box.com/folders/123456789", "123456789"),
    ],
)
def test_parse_box_folder_id(value: str, expected: str) -> None:
    assert parse_box_folder_id(value) == expected


def test_parse_box_folder_id_rejects_non_folder_url() -> None:
    with pytest.raises(ConnectorValidationError):
        parse_box_folder_id("https://app.box.com/file/123456789")

    with pytest.raises(ConnectorValidationError):
        parse_box_folder_id("https://example.com/folder/123456789")


@pytest.mark.parametrize("value", ["", "abc123", "123-456"])
def test_parse_box_folder_id_rejects_non_numeric_id(value: str) -> None:
    with pytest.raises(ConnectorValidationError):
        parse_box_folder_id(value)


def test_normalize_url() -> None:
    result = BoxConnector.normalize_url("https://app.box.com/file/999?p=1")
    assert result.normalized_url == "box-file-999"
    assert result.use_default is False

    non_box = BoxConnector.normalize_url("https://evil.com/file/999")
    assert non_box.normalized_url is None
    assert non_box.use_default is False

    # suffix-spoofed domain must not match
    spoofed = BoxConnector.normalize_url("https://app.box.com.evil.com/file/999")
    assert spoofed.normalized_url is None


def _connector_with_users(
    users_by_login: dict[str, str],
    users_fail_status: int | None = None,
) -> BoxConnector:
    connector = BoxConnector()
    fake = FakeBoxClient(
        folders_by_id={},
        pages={},
        users_by_login=users_by_login,
        users_fail_status=users_fail_status,
    )
    connector._enterprise_client = cast(BoxClient, fake)
    return connector


def test_resolve_user_id_from_email() -> None:
    connector = _connector_with_users(
        {"admin@example.com": "111", "someone.else@example.com": "222"}
    )
    assert connector._resolve_user_id_from_email("admin@example.com") == "111"
    # case-insensitive + surrounding whitespace
    assert connector._resolve_user_id_from_email("  Admin@Example.com ") == "111"


def test_resolve_user_id_requires_exact_login_match() -> None:
    # Box filter_term is a prefix match, so a prefix of a real login returns a
    # candidate the connector must reject rather than mis-impersonate.
    connector = _connector_with_users({"admin@example.com": "111"})
    with pytest.raises(ConnectorValidationError):
        connector._resolve_user_id_from_email("admin@examp")


def test_resolve_user_id_not_found() -> None:
    connector = _connector_with_users({"admin@example.com": "111"})
    with pytest.raises(ConnectorValidationError):
        connector._resolve_user_id_from_email("nobody@example.com")


def test_resolve_user_id_maps_403_to_insufficient_permissions() -> None:
    connector = _connector_with_users({}, users_fail_status=403)
    with pytest.raises(InsufficientPermissionsError) as exc_info:
        connector._resolve_user_id_from_email("admin@example.com")
    assert exc_info.value.__cause__ is not None


@pytest.mark.parametrize(
    "status,expected_error",
    [
        (401, CredentialExpiredError),
        (404, CredentialExpiredError),
        (403, InsufficientPermissionsError),
        (500, UnexpectedValidationError),
    ],
)
def test_identity_validation_preserves_box_api_error(
    status: int,
    expected_error: type[Exception],
) -> None:
    connector = BoxConnector()
    client = MagicMock()
    box_error = make_box_api_error(status)
    client.users.get_user_me.side_effect = box_error
    connector._auth = cast(BoxCCGAuth, MagicMock())
    connector._content_client = cast(BoxClient, client)

    with pytest.raises(expected_error) as exc_info:
        connector.validate_connector_settings()

    assert exc_info.value.__cause__ is box_error


@pytest.mark.parametrize(
    "status,expected_error",
    [
        (403, InsufficientPermissionsError),
        (404, ConnectorValidationError),
        (500, UnexpectedValidationError),
    ],
)
def test_folder_validation_preserves_box_api_error(
    status: int,
    expected_error: type[Exception],
) -> None:
    connector = BoxConnector()
    client = MagicMock()
    box_error = make_box_api_error(status)
    client.folders.get_folder_by_id.side_effect = box_error
    connector._auth = cast(BoxCCGAuth, MagicMock())
    connector._content_client = cast(BoxClient, client)

    with pytest.raises(expected_error) as exc_info:
        connector.validate_connector_settings()

    assert exc_info.value.__cause__ is box_error


def test_load_credentials_defers_clients_and_impersonation_lookup() -> None:
    connector = BoxConnector()
    connector.load_credentials(
        {
            "box_client_id": "client",
            "box_client_secret": "secret",
            "box_enterprise_id": "enterprise",
            "box_user_email": "user@example.com",
        }
    )

    assert connector._enterprise_client is None
    assert connector._content_client is None
    assert connector._user_email == "user@example.com"

    connector.enterprise_client

    assert connector._enterprise_client is not None
    assert connector._content_client is None


def test_fresh_connector_resumes_from_serialized_checkpoint() -> None:
    """Each indexing cycle can run in a new process, so a brand-new connector
    must resume purely from the serialized checkpoint — no instance state may
    leak between cycles. Rebuild the connector (and its client) every cycle and
    assert the output matches a single long-lived instance."""
    single = [
        o.id
        for o in _run_to_completion(_make_connector(_build_fake_client()))
        if isinstance(o, Document)
    ]

    checkpoint_json = _make_connector(_build_fake_client()).build_dummy_checkpoint()
    checkpoint = checkpoint_json
    resumed: list[str] = []
    iterations = 0
    while checkpoint.has_more:
        iterations += 1
        assert iterations < 100, "traversal did not terminate"
        # fresh connector + fresh client each cycle, seeded only by the checkpoint
        connector = _make_connector(_build_fake_client())
        generator = connector.load_from_checkpoint(_START, _END, checkpoint)
        while True:
            try:
                item = next(generator)
                if isinstance(item, Document):
                    resumed.append(item.id)
            except StopIteration as e:
                checkpoint = BoxConnector(folder_ids=["100"]).validate_checkpoint_json(
                    e.value.model_dump_json()
                )
                break

    assert sorted(resumed) == sorted(single)


def test_at_most_one_folder_page_per_checkpoint_cycle() -> None:
    fake_client = _build_fake_client()
    connector = _make_connector(fake_client)
    checkpoint = connector.build_dummy_checkpoint()

    while checkpoint.has_more:
        before = len(fake_client.folders.listing_calls)
        generator = connector.load_from_checkpoint(_START, _END, checkpoint)
        while True:
            try:
                next(generator)
            except StopIteration as e:
                checkpoint = connector.validate_checkpoint_json(
                    e.value.model_dump_json()
                )
                break
        # a single cycle may seed, start a folder, or read one page — never more
        # than one listing call, so checkpoints stay small and resumable
        assert len(fake_client.folders.listing_calls) - before <= 1


def test_overlapping_entry_folders_not_double_indexed() -> None:
    # "200" is a child of "100"; configuring both (plus a literal duplicate)
    # must not index Sub's contents or re-yield its hierarchy node twice.
    fake_client = _build_fake_client()
    connector = _make_connector(fake_client, folder_ids=["100", "200", "100"])
    outputs = _run_to_completion(connector)

    doc_ids = [o.id for o in outputs if isinstance(o, Document)]
    node_ids = [o.raw_node_id for o in outputs if isinstance(o, HierarchyNode)]

    assert sorted(doc_ids) == ["box-file-1", "box-file-3"]  # each exactly once
    assert doc_ids.count("box-file-3") == 1
    assert node_ids.count("200") == 1
    assert node_ids.count("100") == 1
