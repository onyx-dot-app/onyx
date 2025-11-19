import importlib
from typing import Any
from typing import Type

from sqlalchemy.orm import Session

from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.constants import DocumentSource
from onyx.configs.llm_configs import get_image_extraction_and_analysis_enabled
from onyx.connectors.credentials_provider import OnyxDBCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CredentialsConnector
from onyx.connectors.interfaces import EventConnector
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.models import InputType
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.db.connector import fetch_connector_by_id
from onyx.db.credentials import backend_update_credential_json
from onyx.db.credentials import fetch_credential_by_id
from onyx.db.enums import AccessType
from onyx.db.models import Credential
from shared_configs.contextvars import get_current_tenant_id


class ConnectorMissingException(Exception):
    pass


# Cache for already imported connector classes
_connector_cache: dict[DocumentSource, Type[BaseConnector]] = {}


def _load_connector_class(source: DocumentSource) -> Type[BaseConnector]:
    """Dynamically load and cache a connector class."""
    if source in _connector_cache:
        return _connector_cache[source]

    if source not in CONNECTOR_CLASS_MAP:
        raise ConnectorMissingException(f"Connector not found for source={source}")

    mapping = CONNECTOR_CLASS_MAP[source]

    try:
        module = importlib.import_module(mapping.module_path)
        connector_class = getattr(module, mapping.class_name)
        _connector_cache[source] = connector_class
        return connector_class
    except (ImportError, AttributeError) as e:
        raise ConnectorMissingException(
            f"Failed to import {mapping.class_name} from {mapping.module_path}: {e}"
        )


def _validate_connector_supports_input_type(
    connector: Type[BaseConnector],
    input_type: InputType | None,
    source: DocumentSource,
) -> None:
    """Validate that a connector supports the requested input type."""
    if input_type is None:
        return

    # Check each input type requirement separately for clarity
    load_state_unsupported = input_type == InputType.LOAD_STATE and not issubclass(
        connector, LoadConnector
    )

    poll_unsupported = (
        input_type == InputType.POLL
        # Either poll or checkpoint works for this, in the future
        # all connectors should be checkpoint connectors
        and (
            not issubclass(connector, PollConnector)
            and not issubclass(connector, CheckpointedConnector)
        )
    )

    event_unsupported = input_type == InputType.EVENT and not issubclass(
        connector, EventConnector
    )

    if any([load_state_unsupported, poll_unsupported, event_unsupported]):
        raise ConnectorMissingException(
            f"Connector for source={source} does not accept input_type={input_type}"
        )


def identify_connector_class(
    source: DocumentSource,
    input_type: InputType | None = None,
) -> Type[BaseConnector]:
    # Load the connector class using lazy loading
    connector = _load_connector_class(source)

    # Validate connector supports the requested input_type
    _validate_connector_supports_input_type(connector, input_type, source)

    return connector


def instantiate_connector(
    db_session: Session,
    source: DocumentSource,
    input_type: InputType,
    connector_specific_config: dict[str, Any],
    credential: Credential,
) -> BaseConnector:
    connector_class = identify_connector_class(source, input_type)

    connector = connector_class(**connector_specific_config)

    if isinstance(connector, CredentialsConnector):
        provider = OnyxDBCredentialsProvider(
            get_current_tenant_id(), str(source), credential.id
        )
        connector.set_credentials_provider(provider)
    else:
        new_credentials = connector.load_credentials(credential.credential_json)

        if new_credentials is not None:
            backend_update_credential_json(credential, new_credentials, db_session)

    connector.set_allow_images(get_image_extraction_and_analysis_enabled())

    return connector


def validate_ccpair_for_user(
    connector_id: int,
    credential_id: int,
    access_type: AccessType,
    db_session: Session,
    enforce_creation: bool = True,
) -> bool:
    if INTEGRATION_TESTS_MODE:
        return True

    # Validate the connector settings
    connector = fetch_connector_by_id(connector_id, db_session)
    credential = fetch_credential_by_id(
        credential_id,
        db_session,
    )

    if not connector:
        raise ValueError("Connector not found")

    if (
        connector.source == DocumentSource.INGESTION_API
        or connector.source == DocumentSource.MOCK_CONNECTOR
    ):
        return True

    if not credential:
        raise ValueError("Credential not found")

    try:
        runnable_connector = instantiate_connector(
            db_session=db_session,
            source=connector.source,
            input_type=connector.input_type,
            connector_specific_config=connector.connector_specific_config,
            credential=credential,
        )
    except ConnectorValidationError as e:
        raise e
    except Exception as e:
        if enforce_creation:
            raise ConnectorValidationError(str(e))
        else:
            return False

    runnable_connector.validate_connector_settings()
    if access_type == AccessType.SYNC:
        runnable_connector.validate_perm_sync()
    return True
