import importlib
from enum import Enum
from typing import Any, Type

import pydantic
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.constants import DocumentSource
from onyx.configs.llm_configs import get_image_extraction_and_analysis_enabled
from onyx.connectors.capability_checks.recorder import (
    record_blocking_validation_outcome,
)
from onyx.connectors.connector_config import CredentialBinding
from onyx.connectors.credential_families import to_source_credential_json
from onyx.connectors.credentials_provider import build_db_credentials_provider
from onyx.connectors.exceptions import ConnectorValidationError, ValidationError
from onyx.connectors.interfaces import (
    BaseConnector,
    CheckpointedConnector,
    CredentialsConnector,
    LoadConnector,
    PollConnector,
)
from onyx.connectors.models import InputType
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.db.connector import fetch_connector_by_id
from onyx.db.credentials import backend_update_credential_json, fetch_credential_by_id
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from onyx.db.models import Credential
from onyx.file_store.staging import RawFileCallback
from onyx.utils.credential_audit import emit_credential_access
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
        connector_class = getattr(module, mapping.class_name)  # ods: ignore[getattr]
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

    event_unsupported = input_type == InputType.EVENT

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


def split_comma_separated_config_fields(
    source: DocumentSource, connector_specific_config: dict[str, Any]
) -> dict[str, Any]:
    """Returns the config with the source's comma-separated list fields split
    into one value per entry."""
    mapping = CONNECTOR_CLASS_MAP.get(source)
    if mapping is None:
        return connector_specific_config
    return mapping.config_class.split_comma_separated_fields(connector_specific_config)


def validate_connector_config(
    source: DocumentSource, connector_specific_config: dict[str, Any]
) -> None:
    """Raises ``pydantic.ValidationError`` (a ``ValueError``) if the config does
    not match the source's typed config. Sources without a connector class
    (e.g. ingestion API) are not checked."""
    mapping = CONNECTOR_CLASS_MAP.get(source)
    if mapping is None:
        return
    mapping.config_class.model_validate(connector_specific_config)


def build_connector_kwargs(
    source: DocumentSource, connector_specific_config: dict[str, Any]
) -> dict[str, Any]:
    """Validates a stored config into the ``__init__`` kwargs of the connector.

    Only keys present in the stored config are passed, so constructor defaults
    still apply. A stored config that fails validation is passed through as-is,
    since rows written before typed configs existed may not conform.
    """
    mapping = CONNECTOR_CLASS_MAP.get(source)
    if mapping is None:
        return connector_specific_config
    try:
        config = mapping.config_class.model_validate(connector_specific_config)
    except pydantic.ValidationError as e:
        # TODO(evan-onyx): raise here once no stored config fails validation.
        logger.warning(
            "Stored connector config does not match its typed config; using it as-is: source=%s errors=%s",
            source,
            e,
        )
        return connector_specific_config
    return config.model_dump(exclude_unset=True)


def instantiate_connector(
    db_session: Session,
    source: DocumentSource,
    input_type: InputType | None,
    connector_specific_config: dict[str, Any],
    credential: Credential,
    raw_file_callback: RawFileCallback | None = None,
) -> BaseConnector:
    connector_class = identify_connector_class(source, input_type)

    connector = connector_class(
        **build_connector_kwargs(source, connector_specific_config)
    )

    if isinstance(connector, CredentialsConnector):
        provider = build_db_credentials_provider(source, credential.id)
        connector.set_credentials_provider(provider)
    else:
        if credential.credential_json:
            # Distinct decrypt site from OnyxDBCredentialsProvider (static /
            # non-dynamic connectors load creds directly here), so this is not
            # double-logged. Audit is best-effort and never raises.
            emit_credential_access(
                credential_type="connector",
                provider=str(source),
                row_id=credential.id,
            )
        credential_json = to_source_credential_json(
            source,
            (
                credential.credential_json.get_value(apply_mask=False)
                if credential.credential_json
                else {}
            ),
        )
        new_credentials = connector.load_credentials(credential_json)

        if new_credentials is not None:
            backend_update_credential_json(
                credential, source, new_credentials, db_session
            )

    connector.set_allow_images(get_image_extraction_and_analysis_enabled())

    if raw_file_callback is not None:
        connector.set_raw_file_callback(raw_file_callback)

    return connector


def _credential_binding_class(
    source: DocumentSource,
) -> type[CredentialBinding] | None:
    mapping = CONNECTOR_CLASS_MAP.get(source)
    return mapping.config_class.credential_binding_class() if mapping else None


def parse_credential_binding(
    source: DocumentSource, connector_specific_config: dict[str, Any]
) -> CredentialBinding | None:
    """The config's credential-bound values, or ``None`` if the source has no
    binding model or the stored config does not match it (rows written before
    typed configs existed may not conform)."""
    binding_class = _credential_binding_class(source)
    if binding_class is None:
        return None
    try:
        return binding_class.model_validate(connector_specific_config)
    except pydantic.ValidationError as e:
        logger.warning(
            "Stored connector config does not match its binding model: source=%s errors=%s",
            source,
            e,
        )
        return None


def validate_credential_binding(
    source: DocumentSource,
    connector_specific_config: dict[str, Any],
    credential: Credential,
) -> None:
    """Raises ``ConnectorValidationError`` if the config's credential-bound
    values cannot be used with the credential, or cannot be checked because they
    do not match the source's binding model."""
    # A source without a connector class fails at instantiation with a clearer
    # error.
    binding_class = _credential_binding_class(source)
    # Skip the decrypt when the source has no binding rule.
    if (
        binding_class is None
        or binding_class.validate_credential is CredentialBinding.validate_credential
    ):
        return
    try:
        binding = binding_class.model_validate(connector_specific_config)
    except pydantic.ValidationError as e:
        raise ConnectorValidationError(
            f"The connector's credential-bound settings are invalid: {e}"
        ) from e
    if not credential.credential_json:
        return
    emit_credential_access(
        credential_type="connector", provider=str(source), row_id=credential.id
    )
    binding.validate_credential(
        to_source_credential_json(
            source, credential.credential_json.get_value(apply_mask=False)
        )
    )


class CredentialBindingFieldErrorKind(str, Enum):
    MISSING = "missing"
    INVALID = "invalid"


class CredentialBindingFieldError(BaseModel):
    kind: CredentialBindingFieldErrorKind
    # English text from the binding model's validation. Clients show their
    # own message for ``kind`` and may add this as detail.
    detail: str


_MISSING_FIELD_DETAIL = "This field is required."


def credential_binding_field_errors(
    source: DocumentSource, connector_specific_config: dict[str, Any]
) -> dict[str, CredentialBindingFieldError]:
    """Field name to error for the config's credential-bound fields. A required
    bound field that is absent or blank is ``MISSING``. Empty when the source
    has no binding model. Details never echo the input value."""
    binding_class = _credential_binding_class(source)
    if binding_class is None:
        return {}
    errors: dict[str, CredentialBindingFieldError] = {}
    for name, field in binding_class.model_fields.items():
        value = connector_specific_config.get(name)
        if field.is_required() and (
            value is None or (isinstance(value, str) and not value.strip())
        ):
            errors[name] = CredentialBindingFieldError(
                kind=CredentialBindingFieldErrorKind.MISSING,
                detail=_MISSING_FIELD_DETAIL,
            )
    try:
        binding_class.model_validate(
            {
                name: value
                for name, value in connector_specific_config.items()
                if name in binding_class.model_fields and name not in errors
            }
        )
    except pydantic.ValidationError as e:
        for detail in e.errors():
            loc = detail["loc"]
            name = str(loc[0]) if loc else ""
            if name in binding_class.model_fields and name not in errors:
                errors[name] = CredentialBindingFieldError(
                    kind=CredentialBindingFieldErrorKind.INVALID,
                    detail=str(detail["msg"]),
                )
    return errors


def validate_connector_credential_bindings(
    connector_id: int,
    source: DocumentSource,
    connector_specific_config: dict[str, Any],
    db_session: Session,
) -> None:
    """Raises ``ConnectorValidationError`` if the config cannot be used with a
    credential the connector is already paired with. Config edits call this;
    pairing checks the binding in ``validate_ccpair_for_user``."""
    connector = fetch_connector_by_id(connector_id, db_session)
    if connector is None:
        return
    for cc_pair in connector.credentials:
        validate_credential_binding(
            source, connector_specific_config, cc_pair.credential
        )


def validate_ccpair_for_user(
    connector_id: int,
    credential_id: int,
    access_type: AccessType,
    db_session: Session,
    enforce_creation: bool = True,
    trigger: CapabilityCheckTrigger = CapabilityCheckTrigger.CC_PAIR_VALIDATION,
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

    # Plain values for the closure: it runs inside exception handlers, where
    # lazy ORM attribute loads can raise (e.g. ``PendingRollbackError``) and
    # replace the exception being handled.
    source = connector.source
    connector_specific_config = connector.connector_specific_config

    def _record_outcome(error: Exception | None, perm_sync_validated: bool) -> None:
        # Best-effort scribe for the outcome below; never raises and never
        # touches this function's session or semantics.
        record_blocking_validation_outcome(
            credential_id=credential_id,
            connector_id=connector_id,
            source=source,
            trigger=trigger,
            error=error,
            perm_sync_validated=perm_sync_validated,
            connector_specific_config=connector_specific_config,
        )

    # Inline imports: the creation module imports the runner, which imports
    # this module, and the registry eagerly imports every migrated connector's
    # check module.
    from onyx.connectors.capability_checks.creation import (
        validate_pairing_with_named_checks,
    )
    from onyx.connectors.capability_checks.registry import (
        has_named_capability_checks,
    )

    # Creation and credential swap run the named checks; indexing and perm-sync
    # attempts keep the legacy validation.
    use_named_checks = (
        trigger == CapabilityCheckTrigger.CC_PAIR_VALIDATION
        and has_named_capability_checks(source)
    )
    try:
        validate_credential_binding(source, connector_specific_config, credential)
        # Construction validates parts of the config (for example the Microsoft
        # hosts), so it gates both paths.
        runnable_connector = instantiate_connector(
            db_session=db_session,
            source=connector.source,
            input_type=connector.input_type,
            connector_specific_config=connector.connector_specific_config,
            credential=credential,
        )
        if not use_named_checks:
            runnable_connector.validate_connector_settings()
            if access_type.is_perm_synced():
                runnable_connector.validate_perm_sync()
    except ValidationError as e:
        _record_outcome(e, perm_sync_validated=False)
        raise
    except Exception as e:
        # Record ``e`` itself: wrapping first would misreport an unexpected
        # error as FAILED and erase the real ``error_type``.
        _record_outcome(e, perm_sync_validated=False)
        if enforce_creation:
            raise ConnectorValidationError(str(e))
        return False

    if use_named_checks:
        return validate_pairing_with_named_checks(
            connector_id=connector_id,
            source=source,
            input_type=connector.input_type,
            connector_specific_config=connector_specific_config,
            credential=credential,
            access_type=access_type,
            enforce_creation=enforce_creation,
        )

    _record_outcome(None, perm_sync_validated=access_type.is_perm_synced())
    return True
