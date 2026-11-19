import threading

from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import IntegrationAuthMethod, IntegrationAuthMode, IntegrationKind
from onyx.db.integration import (
    get_mcp_admin_config,
    list_integration_actions,
    list_unsynced_integration_ids,
    lock_integration__no_commit,
    lock_unsynced_integration__no_commit,
    mark_integration_synced__no_commit,
    replace_integration_actions__no_commit,
)
from onyx.db.models import Integration
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.connections import credential_fields_json
from onyx.integrations.kinds.api import ApiKindHandler
from onyx.server.features.mcp.models import DENYLISTED_MCP_HEADERS
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The schemas that this process found with no unsynced integration.
_synced_schemas: set[str] = set()
_syncing_schemas: set[str] = set()
_schema_locks: dict[str, threading.RLock] = {}


def sync_integration_actions__no_commit(
    integration: Integration, db_session: Session
) -> None:
    """For an API integration only. A stored source that the kind no longer
    finds loses its rows. The kind settings are read under the integration
    lock, so a sync that started earlier cannot write an older action list
    over a newer one."""
    lock_integration__no_commit(integration.id, db_session)
    specs = ApiKindHandler().discover_actions(integration, db_session)
    stored_sources = {
        action.source for action in list_integration_actions(integration.id, db_session)
    }
    for source in sorted(stored_sources | {spec.source for spec in specs}):
        replace_integration_actions__no_commit(
            integration.id,
            source,
            [spec for spec in specs if spec.source == source],
            db_session,
        )


def _mcp_header_template(config: object) -> dict[str, str] | None:
    """Old configs kept the template in ``headers``."""
    if not isinstance(config, dict):
        return None
    template = config.get("header_template") or config.get("headers")
    if not isinstance(template, dict):
        return None
    return {
        name: value
        for name, value in template.items()
        if isinstance(name, str)
        and isinstance(value, str)
        and name.lower() not in DENYLISTED_MCP_HEADERS
    } or None


def _copy_mcp_header_template(integration: Integration, db_session: Session) -> None:
    """A per-user API key MCP server kept its header template in the
    encrypted admin config. A config that does not read leaves no template,
    and the admin list shows the integration as not set up."""
    config = get_mcp_admin_config(integration.id, db_session)
    if config is None:
        return
    try:
        value = config.get_value(apply_mask=False)
    except Exception as error:
        logger.warning(
            "Integration %s: the MCP admin config does not read (%s)",
            integration.id,
            type(error).__name__,
        )
        return
    template = _mcp_header_template(value)
    if template is None:
        return
    integration.header_template = template
    integration.credential_fields = credential_fields_json(None, template)


def sync_new_integration__no_commit(integration_id: int, db_session: Session) -> None:
    """Fill the data of a migrated integration that only app code can read,
    then mark it synced. A source that does not read gives no data and is
    not read again."""
    integration = lock_unsynced_integration__no_commit(integration_id, db_session)
    if integration is None:
        return
    if integration.kind is IntegrationKind.API:
        try:
            sync_integration_actions__no_commit(integration, db_session)
        except OnyxError as error:
            logger.warning(
                "Integration %s: the API settings give no actions: %s",
                integration_id,
                error.detail,
            )
    elif (
        integration.auth_mode is IntegrationAuthMode.INDIVIDUAL
        and integration.auth_method is IntegrationAuthMethod.API_KEY
        and integration.header_template is None
    ):
        _copy_mcp_header_template(integration, db_session)
    mark_integration_synced__no_commit(integration, db_session)


def _sync_new_integrations(tenant_id: str) -> bool:
    """True when the schema has no unsynced integration left."""
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        try:
            integration_ids = list_unsynced_integration_ids(db_session)
        except ProgrammingError:
            # The schema does not have the integration tables yet.
            return False
    done = True
    for integration_id in integration_ids:
        try:
            with get_session_with_tenant(tenant_id=tenant_id) as db_session:
                sync_new_integration__no_commit(integration_id, db_session)
                db_session.commit()
        except Exception:
            logger.exception("Integration %s: the first sync failed", integration_id)
            done = False
    return done


def sync_new_integrations_once(tenant_id: str) -> None:
    """Runs before the first database session of a schema in this process.
    The migration of the integration tables cannot read OpenAPI specs, app
    catalogs or encrypted MCP configs, so it leaves synced_at NULL and app
    code fills that data here, before any reader of the schema runs. The
    row lock and the synced_at check make concurrent processes safe. The
    sessions this opens come back here and return at once."""
    if tenant_id in _synced_schemas:
        return
    with _schema_locks.setdefault(tenant_id, threading.RLock()):
        if tenant_id in _synced_schemas or tenant_id in _syncing_schemas:
            return
        _syncing_schemas.add(tenant_id)
        try:
            if _sync_new_integrations(tenant_id):
                _synced_schemas.add(tenant_id)
        except Exception:
            logger.exception(
                "The first sync of the integrations of %s failed", tenant_id
            )
        finally:
            _syncing_schemas.discard(tenant_id)
