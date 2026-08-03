from functools import cached_property

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors import source_operations as source_operations_module
from onyx.connectors.capability_checks.models import CredentialCapability
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    get_source_operations_class,
    registered_source_operations,
    source_operation,
)


@pytest.fixture
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolates the gateway registry so test classes never leak globally."""
    monkeypatch.setattr(source_operations_module, "_SOURCE_OPERATIONS_BY_SOURCE", {})


@pytest.mark.usefixtures("isolated_registry")
def test_gateway_registers_and_collects_specs() -> None:
    """Verifies stamped methods register with their metadata intact."""

    # Precondition and under test (registration fires at class creation).
    class _SlackOperations(SourceOperations):
        source = DocumentSource.SLACK

        @source_operation(
            capabilities={CredentialCapability.INDEXING},
            consumes=OperationConsumes.CREDENTIAL,
            variants=("public", "private"),
        )
        def list_channels(self, _private: bool) -> list[str]:
            return []

        @source_operation(
            capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
            consumes=OperationConsumes.NEITHER,
            untested="Dormant by design.",
        )
        def list_usergroups(self) -> list[str]:
            return []

    # Postcondition.
    assert get_source_operations_class(DocumentSource.SLACK) is _SlackOperations
    assert registered_source_operations() == {DocumentSource.SLACK: _SlackOperations}
    specs = _SlackOperations.operation_specs()
    assert set(specs) == {"list_channels", "list_usergroups"}
    assert specs["list_channels"].capabilities == {CredentialCapability.INDEXING}
    assert specs["list_channels"].variants == ("public", "private")
    assert specs["list_channels"].consumes == OperationConsumes.CREDENTIAL
    assert specs["list_channels"].untested is None
    assert specs["list_usergroups"].untested == "Dormant by design."


@pytest.mark.usefixtures("isolated_registry")
def test_unstamped_public_method_fails_at_import() -> None:
    """
    Verifies the forcing function: unclassified public methods cannot exist.
    """
    # Under test and postcondition.
    with pytest.raises(TypeError, match="unclassified public methods.*fetch_page"):

        class _LeakyOperations(SourceOperations):
            source = DocumentSource.SLACK

            def fetch_page(self) -> None:
                return None


@pytest.mark.usefixtures("isolated_registry")
def test_missing_source_fails_at_import() -> None:
    """Verifies a gateway must declare which source it serves."""
    # Under test and postcondition.
    with pytest.raises(TypeError, match="must set ``source``"):

        class _SourcelessOperations(SourceOperations):
            pass


@pytest.mark.usefixtures("isolated_registry")
def test_non_document_source_fails_at_import() -> None:
    """Verifies ``source`` must be a DocumentSource, not a lookalike string."""
    # Under test and postcondition.
    with pytest.raises(TypeError, match="must set ``source``"):

        class _StringSourceOperations(SourceOperations):
            source = "slack"  # type: ignore[assignment]


@pytest.mark.usefixtures("isolated_registry")
def test_mixin_bases_are_rejected() -> None:
    """
    Verifies mixins cannot smuggle unscanned public methods past enforcement.
    """

    # Precondition.
    class _PaginationMixin:
        def fetch_all_pages(self) -> None:
            return None

    # Under test and postcondition.
    with pytest.raises(TypeError, match="directly and nothing else"):

        class _MixedOperations(_PaginationMixin, SourceOperations):
            source = DocumentSource.SLACK


@pytest.mark.usefixtures("isolated_registry")
def test_gateway_inheritance_is_rejected() -> None:
    """
    Verifies a gateway cannot be subclassed: inherited operations would be
    invisible to ``operation_specs`` and silently under-counted by coverage.
    """

    # Precondition.
    class _SlackOperations(SourceOperations):
        source = DocumentSource.SLACK

    # Under test and postcondition.
    with pytest.raises(TypeError, match="directly and nothing else"):

        class _SlackCloudOperations(_SlackOperations):
            source = DocumentSource.GITHUB


@pytest.mark.usefixtures("isolated_registry")
def test_duplicate_source_registration_fails() -> None:
    """Verifies the one-gateway-per-source rule."""

    # Precondition.
    class _FirstOperations(SourceOperations):
        source = DocumentSource.SLACK

    # Under test and postcondition.
    with pytest.raises(TypeError, match="already registered by _FirstOperations"):

        class _SecondOperations(SourceOperations):
            source = DocumentSource.SLACK


@pytest.mark.usefixtures("isolated_registry")
def test_private_helpers_and_data_attrs_are_allowed() -> None:
    """Verifies enforcement only targets public methods."""

    # Under test.
    class _TidyOperations(SourceOperations):
        source = DocumentSource.SLACK
        docs_link = "https://docs.onyx.app/connectors/slack"

        def _build_client(self) -> None:
            return None

        @staticmethod
        def _parse_page(page: dict) -> dict:
            return page

    # Postcondition.
    assert _TidyOperations.operation_specs() == {}


@pytest.mark.usefixtures("isolated_registry")
def test_public_staticmethod_is_rejected() -> None:
    """Verifies public non-instance-method callables cannot slip through."""
    # Under test and postcondition.
    with pytest.raises(TypeError, match="make it private"):

        class _StaticOperations(SourceOperations):
            source = DocumentSource.SLACK

            @staticmethod
            def build_client() -> None:
                return None


@pytest.mark.usefixtures("isolated_registry")
def test_public_property_is_rejected() -> None:
    """Verifies properties cannot bypass classification either."""
    # Under test and postcondition.
    with pytest.raises(TypeError, match="make it private"):

        class _PropertyOperations(SourceOperations):
            source = DocumentSource.SLACK

            @property
            def team_id(self) -> str:
                return ""


@pytest.mark.usefixtures("isolated_registry")
def test_public_non_callable_descriptor_is_rejected() -> None:
    """
    Verifies descriptors like ``cached_property`` cannot pass as data
    attributes: they execute on attribute access, the lazy-call hazard the
    gateway exists to contain.
    """
    # Under test and postcondition.
    with pytest.raises(TypeError, match="public descriptor"):

        class _CachedPropertyOperations(SourceOperations):
            source = DocumentSource.SLACK

            @cached_property
            def team_id(self) -> str:
                return ""


@pytest.mark.usefixtures("isolated_registry")
def test_public_classmethod_is_rejected() -> None:
    """Verifies classmethods cannot bypass classification either."""
    # Under test and postcondition.
    with pytest.raises(TypeError, match="make it private"):

        class _ClassmethodOperations(SourceOperations):
            source = DocumentSource.SLACK

            @classmethod
            def build_client(cls) -> None:
                return None


@pytest.mark.usefixtures("isolated_registry")
def test_public_nested_class_is_rejected() -> None:
    """Verifies nested classes get their own accurate rejection message."""
    # Under test and postcondition.
    with pytest.raises(TypeError, match="define data models at module level"):

        class _NestedModelOperations(SourceOperations):
            source = DocumentSource.SLACK

            class Channel:
                pass


@pytest.mark.usefixtures("isolated_registry")
def test_aliased_operation_assignment_is_rejected() -> None:
    """Verifies a stamped operation cannot register under a different name."""

    # Precondition.
    def _shared_impl(_self: SourceOperations) -> None:
        return None

    stamped = source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )(_shared_impl)

    # Under test and postcondition.
    with pytest.raises(TypeError, match="aliased assignment"):

        class _AliasedOperations(SourceOperations):
            source = DocumentSource.SLACK
            list_a = stamped


def test_base_operation_specs_is_empty() -> None:
    """Verifies the accessor is total on the base class itself."""
    # Under test and postcondition.
    assert SourceOperations.operation_specs() == {}


def test_decorator_rejects_empty_capabilities() -> None:
    """Verifies an operation must serve at least one capability."""
    # Under test and postcondition.
    with pytest.raises(ValueError, match="at least one capability"):
        source_operation(capabilities=set(), consumes=OperationConsumes.CREDENTIAL)


@pytest.mark.usefixtures("isolated_registry")
def test_decorator_snapshots_capabilities_at_factory_time() -> None:
    """
    Verifies the capability set is snapped and validated atomically: mutating
    the caller's collection after the factory call changes nothing.
    """
    # Precondition.
    capabilities = {CredentialCapability.INDEXING}
    decorator = source_operation(
        capabilities=capabilities, consumes=OperationConsumes.CREDENTIAL
    )
    capabilities.clear()

    # Under test.
    class _SnapshotOperations(SourceOperations):
        source = DocumentSource.SLACK

        @decorator
        def probe(self) -> None:
            return None

    # Postcondition.
    assert _SnapshotOperations.operation_specs()["probe"].capabilities == {
        CredentialCapability.INDEXING
    }


def test_decorator_rejects_blank_untested_reason() -> None:
    """Verifies the untested exemption cannot be claimed without a reason."""
    # Under test and postcondition.
    with pytest.raises(ValueError, match="non-empty reason"):
        source_operation(
            capabilities={CredentialCapability.INDEXING},
            consumes=OperationConsumes.CREDENTIAL,
            untested="   ",
        )


def test_decorator_rejects_duplicate_variants() -> None:
    """Verifies variant names must be unique."""
    # Under test and postcondition.
    with pytest.raises(ValueError, match="Duplicate variants"):
        source_operation(
            capabilities={CredentialCapability.INDEXING},
            consumes=OperationConsumes.CREDENTIAL,
            variants=("public", "public"),
        )


def test_decorator_rejects_blank_variant_names() -> None:
    """Verifies variant names must be non-empty."""
    # Under test and postcondition.
    with pytest.raises(ValueError, match="Variant names must be non-empty"):
        source_operation(
            capabilities={CredentialCapability.INDEXING},
            consumes=OperationConsumes.CREDENTIAL,
            variants=("public", ""),
        )
