from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, ConfigDict

from onyx.connectors.field_policy import FieldClass, FieldPolicy
from onyx.db.enums import HierarchyNodeType


class CredentialBinding(BaseModel):
    """The config fields whose valid values depend on the account behind the
    credential, e.g. a site URL, a cloud vs. data center flag, or a national-cloud
    host. A connector config inherits its binding model, so the stored config
    stays flat. Validated on its own from a full config, it ignores the other keys.
    """

    # Fields whose value the form takes from the credential itself and that
    # ``validate_credential`` pins to it, e.g. the credential's kind. They name
    # no place to send the credential, so the credential use rule
    # (``factory.assert_user_can_use_credential``) does not compare them.
    credential_derived_fields: ClassVar[frozenset[str]] = frozenset()

    def validate_credential(
        self,
        credential_json: dict[str, Any],  # noqa: ARG002
    ) -> None:
        """Raises ``ConnectorValidationError`` if the credential cannot be used
        with these values. Only checks what the credential itself records; most
        credentials record nothing, so the default accepts every credential."""


class BaseUrlCredentialBinding(CredentialBinding):
    """For sources whose only credential-bound field is the site URL."""

    base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]


class HierarchyBreakdownSection(BaseModel):
    """One node type that the cc-pair status page breaks the documents down by."""

    model_config = ConfigDict(frozen=True)

    node_type: HierarchyNodeType
    # Keys (see ``ConnectorConfig.hierarchy_node_key``) of the nodes that the
    # config names. Each one shows, also when no document is under it.
    expected_node_keys: tuple[str, ...] = ()
    # False shows only the expected nodes of this type.
    include_unexpected_nodes: bool = True
    # True matches the expected keys to the node keys without regard to case.
    case_insensitive_keys: bool = False
    # True when a node of this type can also be a document whose id is the
    # node's raw id (e.g. a Confluence page). An expected node that has no
    # hierarchy node then shows the document, with a count of 1.
    nodes_can_be_documents: bool = False


class ConnectorConfig(BaseModel):
    """Typed shape of a connector's ``connector_specific_config``.

    Each field mirrors one ``__init__`` kwarg of the connector class, with the
    same name, default, and required-ness. ``test_connector_config_models``
    enforces this. Subclasses live in ``<connector>/config.py`` modules, which
    must stay light to import: the registry loads all of them eagerly.
    """

    # extra="forbid" matches the kwargs constructors, where an unknown key is a
    # TypeError. Some configs hold secrets, so errors must not echo input values.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @classmethod
    def credential_binding_class(cls) -> type[CredentialBinding] | None:
        """The most specific binding model this config inherits, if any."""
        return next(
            (
                base
                for base in cls.__mro__
                if issubclass(base, CredentialBinding)
                and not issubclass(base, ConnectorConfig)
            ),
            None,
        )

    def hierarchy_breakdown_sections(self) -> list[HierarchyBreakdownSection] | None:
        """The node types that the status page breaks the documents down by.
        None (the default) uses the top-level nodes: the children of the
        source's root node."""
        return None

    @classmethod
    def hierarchy_node_key(cls, node_type: HierarchyNodeType, raw_node_id: str) -> str:  # noqa: ARG003
        """The id that the config uses for a node. The status page shows it and
        matches it to ``HierarchyBreakdownSection.expected_node_keys``."""
        return raw_node_id
