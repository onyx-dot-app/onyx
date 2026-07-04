"""Fork-only connector registrations merged into CONNECTOR_CLASS_MAP."""

from onyx.configs.constants import DocumentSource
from onyx.connectors.registry import ConnectorMapping

FORK_CONNECTOR_CLASS_MAP: dict[DocumentSource, ConnectorMapping] = {
    DocumentSource.MONDAY: ConnectorMapping(
        module_path="onyx.connectors.monday.connector",
        class_name="MondayConnector",
    ),
}
