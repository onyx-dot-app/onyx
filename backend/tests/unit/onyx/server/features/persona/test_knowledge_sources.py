"""Unit tests for MinimalPersonaSnapshot.from_model knowledge_sources aggregation."""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FederatedConnectorSource
from onyx.server.features.document_set.models import DocumentSetSummary
from onyx.server.features.persona.models import MinimalPersonaSnapshot


_STUB_DS_SUMMARY = DocumentSetSummary(
    id=1,
    name="stub",
    description=None,
    cc_pair_summaries=[],
    is_up_to_date=True,
    is_public=True,
    users=[],
    groups=[],
)


def _make_persona(**overrides: object) -> MagicMock:
    """Build a mock Persona with sensible defaults.

    Every relationship defaults to empty so tests only need to set the
    fields they care about.
    """
    p = MagicMock()
    p.id = 1
    p.name = "test"
    p.description = ""
    p.tools = []
    p.starter_messages = None
    p.document_sets = []
    p.hierarchy_nodes = []
    p.attached_documents = []
    p.user_files = []
    p.llm_model_version_override = None
    p.llm_model_provider_override = None
    p.uploaded_image_id = None
    p.icon_name = None
    p.is_public = True
    p.is_listed = True
    p.display_priority = None
    p.is_featured = False
    p.builtin_persona = False
    p.labels = []
    p.user = None

    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _make_cc_pair(source: DocumentSource) -> MagicMock:
    cc = MagicMock()
    cc.connector.source = source
    cc.name = source.value
    cc.id = 1
    cc.access_type = "PUBLIC"
    return cc


def _make_doc_set(
    cc_pairs: list[MagicMock] | None = None,
    fed_connectors: list[MagicMock] | None = None,
) -> MagicMock:
    ds = MagicMock()
    ds.id = 1
    ds.name = "ds"
    ds.description = None
    ds.is_up_to_date = True
    ds.is_public = True
    ds.users = []
    ds.groups = []
    ds.connector_credential_pairs = cc_pairs or []
    ds.federated_connectors = fed_connectors or []
    return ds


def _make_federated_ds_mapping(
    source: FederatedConnectorSource,
) -> MagicMock:
    mapping = MagicMock()
    mapping.federated_connector.source = source
    mapping.federated_connector_id = 1
    mapping.entities = {}
    return mapping


def _make_hierarchy_node(source: DocumentSource) -> MagicMock:
    node = MagicMock()
    node.source = source
    return node


def _make_attached_document(source: DocumentSource) -> MagicMock:
    doc = MagicMock()
    doc.parent_hierarchy_node = MagicMock()
    doc.parent_hierarchy_node.source = source
    return doc


@patch(
    "onyx.server.features.persona.models.DocumentSetSummary.from_model",
    return_value=_STUB_DS_SUMMARY,
)
def test_empty_persona_has_no_knowledge_sources(_mock_ds: MagicMock) -> None:
    persona = _make_persona()
    snapshot = MinimalPersonaSnapshot.from_model(persona)
    assert snapshot.knowledge_sources == []


@patch(
    "onyx.server.features.persona.models.DocumentSetSummary.from_model",
    return_value=_STUB_DS_SUMMARY,
)
def test_user_files_adds_user_file_source(_mock_ds: MagicMock) -> None:
    persona = _make_persona(user_files=[MagicMock()])
    snapshot = MinimalPersonaSnapshot.from_model(persona)
    assert DocumentSource.USER_FILE in snapshot.knowledge_sources


@patch(
    "onyx.server.features.persona.models.DocumentSetSummary.from_model",
    return_value=_STUB_DS_SUMMARY,
)
def test_no_user_files_excludes_user_file_source(_mock_ds: MagicMock) -> None:
    cc = _make_cc_pair(DocumentSource.CONFLUENCE)
    ds = _make_doc_set(cc_pairs=[cc])
    persona = _make_persona(document_sets=[ds])
    snapshot = MinimalPersonaSnapshot.from_model(persona)
    assert DocumentSource.USER_FILE not in snapshot.knowledge_sources
    assert DocumentSource.CONFLUENCE in snapshot.knowledge_sources


@patch(
    "onyx.server.features.persona.models.DocumentSetSummary.from_model",
    return_value=_STUB_DS_SUMMARY,
)
def test_federated_connector_in_doc_set(_mock_ds: MagicMock) -> None:
    fed = _make_federated_ds_mapping(FederatedConnectorSource.FEDERATED_SLACK)
    ds = _make_doc_set(fed_connectors=[fed])
    persona = _make_persona(document_sets=[ds])
    snapshot = MinimalPersonaSnapshot.from_model(persona)
    assert DocumentSource.SLACK in snapshot.knowledge_sources


@patch(
    "onyx.server.features.persona.models.DocumentSetSummary.from_model",
    return_value=_STUB_DS_SUMMARY,
)
def test_hierarchy_nodes_and_attached_documents(_mock_ds: MagicMock) -> None:
    node = _make_hierarchy_node(DocumentSource.GOOGLE_DRIVE)
    doc = _make_attached_document(DocumentSource.SHAREPOINT)
    persona = _make_persona(hierarchy_nodes=[node], attached_documents=[doc])
    snapshot = MinimalPersonaSnapshot.from_model(persona)
    assert DocumentSource.GOOGLE_DRIVE in snapshot.knowledge_sources
    assert DocumentSource.SHAREPOINT in snapshot.knowledge_sources


@patch(
    "onyx.server.features.persona.models.DocumentSetSummary.from_model",
    return_value=_STUB_DS_SUMMARY,
)
def test_all_source_types_combined(_mock_ds: MagicMock) -> None:
    cc = _make_cc_pair(DocumentSource.CONFLUENCE)
    fed = _make_federated_ds_mapping(FederatedConnectorSource.FEDERATED_SLACK)
    ds = _make_doc_set(cc_pairs=[cc], fed_connectors=[fed])
    node = _make_hierarchy_node(DocumentSource.GOOGLE_DRIVE)
    doc = _make_attached_document(DocumentSource.SHAREPOINT)
    persona = _make_persona(
        document_sets=[ds],
        hierarchy_nodes=[node],
        attached_documents=[doc],
        user_files=[MagicMock()],
    )
    snapshot = MinimalPersonaSnapshot.from_model(persona)
    sources = set(snapshot.knowledge_sources)
    assert sources == {
        DocumentSource.CONFLUENCE,
        DocumentSource.SLACK,
        DocumentSource.GOOGLE_DRIVE,
        DocumentSource.SHAREPOINT,
        DocumentSource.USER_FILE,
    }
