from datetime import datetime

from simple_salesforce.format import format_soql
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import build_db_credentials_provider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.salesforce.auth import build_salesforce_client
from onyx.connectors.salesforce.onyx_salesforce import OnyxSalesforce
from onyx.db.document import get_cc_pairs_for_document
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_SALESFORCE_CLIENT_CACHE: dict[tuple[str, int], tuple[datetime, OnyxSalesforce]] = {}
_CACHED_SF_EMAIL_TO_ID_MAP: dict[tuple[str, OnyxSalesforce, str], str] = {}


def _clear_cached_user_ids_for_client(
    tenant_id: str, sf_client: OnyxSalesforce
) -> None:
    stale_keys = [
        key
        for key in _CACHED_SF_EMAIL_TO_ID_MAP
        if key[0] == tenant_id and key[1] is sf_client
    ]
    for key in stale_keys:
        del _CACHED_SF_EMAIL_TO_ID_MAP[key]


def get_any_salesforce_client_for_doc_id(
    db_session: Session, doc_id: str
) -> OnyxSalesforce:
    """Return the client for the document's first connector credential pair."""
    cc_pairs = get_cc_pairs_for_document(db_session, doc_id)
    if not cc_pairs:
        raise ConnectorValidationError(
            f"No connector credential pair found for Salesforce document: {doc_id}"
        )

    credential = cc_pairs[0].credential
    tenant_id = get_current_tenant_id()
    cache_key = (tenant_id, credential.id)
    cached = _SALESFORCE_CLIENT_CACHE.get(cache_key)
    if cached is not None and cached[0] == credential.time_updated:
        return cached[1]

    provider = build_db_credentials_provider(DocumentSource.SALESFORCE, credential.id)
    client = build_salesforce_client(provider)
    if cached is not None:
        _clear_cached_user_ids_for_client(tenant_id, cached[1])
    _SALESFORCE_CLIENT_CACHE[cache_key] = (credential.time_updated, client)
    return client


def _query_salesforce_user_id(sf_client: OnyxSalesforce, user_email: str) -> str | None:
    query = format_soql(
        "SELECT Id FROM User WHERE Username = {email} AND IsActive = true",
        email=user_email,
    )
    result = sf_client.query(query)
    if len(result["records"]) > 0:
        return result["records"][0]["Id"]

    # Salesforce usernames and emails can differ.
    query = format_soql(
        "SELECT Id FROM User WHERE Email = {email} AND IsActive = true",
        email=user_email,
    )
    result = sf_client.query(query)
    if len(result["records"]) > 0:
        return result["records"][0]["Id"]

    return None


def get_salesforce_user_id_from_email(
    sf_client: OnyxSalesforce,
    user_email: str,
) -> str | None:
    """Resolve a Salesforce user ID, cached by tenant and client identity."""
    cache_key = (get_current_tenant_id(), sf_client, user_email)
    cached_user_id = _CACHED_SF_EMAIL_TO_ID_MAP.get(cache_key)
    if cached_user_id is not None:
        return cached_user_id

    user_id = _query_salesforce_user_id(sf_client, user_email)
    if user_id is None:
        return None

    _CACHED_SF_EMAIL_TO_ID_MAP[cache_key] = user_id
    return user_id


_MAX_RECORD_IDS_PER_QUERY = 200


def get_objects_access_for_user_id(
    salesforce_client: OnyxSalesforce,
    user_id: str,
    record_ids: list[str],
) -> dict[str, bool]:
    """Return access for up to Salesforce's 200 record ID query limit."""
    truncated_record_ids = record_ids[:_MAX_RECORD_IDS_PER_QUERY]
    # SOQL `IN ()` with an empty list is a malformed query, so short-circuit.
    if not truncated_record_ids:
        return {}
    access_query = format_soql(
        """
    SELECT RecordId, HasReadAccess
    FROM UserRecordAccess
    WHERE RecordId IN {record_ids}
    AND UserId = {user_id}
    """,
        record_ids=truncated_record_ids,
        user_id=user_id,
    )
    result = salesforce_client.query_all(access_query)
    return {record["RecordId"]: record["HasReadAccess"] for record in result["records"]}
