from simple_salesforce import Salesforce
from simple_salesforce.format import format_soql
from sqlalchemy.orm import Session

from onyx.db.document import get_cc_pairs_for_document
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Salesforce client per tenant, built from the first cc_pair of the first censored
# doc. Keyed by tenant_id so one tenant's org + credentials are never reused to
# resolve another tenant's access.
_TENANT_SALESFORCE_CLIENT: dict[str, Salesforce] = {}


def get_any_salesforce_client_for_doc_id(
    db_session: Session, doc_id: str
) -> Salesforce:
    """
    Return a cached Salesforce client for the current tenant, building it from the
    first cc_pair of the given doc on first use. Cached to avoid a Postgres lookup
    and a fresh client per query.

    Still imperfect when a tenant has multiple Salesforce cc_pairs with different
    credentials: we use the first, which may lack the permissions the query needs.
    """
    tenant_id = get_current_tenant_id()
    client = _TENANT_SALESFORCE_CLIENT.get(tenant_id)
    if client is None:
        cc_pairs = get_cc_pairs_for_document(db_session, doc_id)
        first_cc_pair = cc_pairs[0]
        credential_json = (
            first_cc_pair.credential.credential_json.get_value(apply_mask=False)
            if first_cc_pair.credential.credential_json
            else {}
        )
        client = Salesforce(
            username=credential_json["sf_username"],
            password=credential_json["sf_password"],
            security_token=credential_json["sf_security_token"],
        )
        _TENANT_SALESFORCE_CLIENT[tenant_id] = client
    return client


def _query_salesforce_user_id(sf_client: Salesforce, user_email: str) -> str | None:
    query = format_soql(
        "SELECT Id FROM User WHERE Username = {email} AND IsActive = true",
        email=user_email,
    )
    result = sf_client.query(query)
    if len(result["records"]) > 0:
        return result["records"][0]["Id"]

    # try emails
    query = format_soql(
        "SELECT Id FROM User WHERE Email = {email} AND IsActive = true",
        email=user_email,
    )
    result = sf_client.query(query)
    if len(result["records"]) > 0:
        return result["records"][0]["Id"]

    return None


# (tenant_id, user_email) -> Salesforce user_id. Keyed by tenant so a shared email
# never resolves to another tenant's Salesforce user. Only real (non-None) ids are
# stored; unknown emails are re-queried each call.
_CACHED_SF_EMAIL_TO_ID_MAP: dict[tuple[str, str], str] = {}


def get_salesforce_user_id_from_email(
    sf_client: Salesforce,
    user_email: str,
) -> str | None:
    """
    Resolve a Salesforce user_id for an email, cached per tenant since Salesforce
    user ids are stable. A miss queries Salesforce (~0.1-0.3s); a hit is ~instant.
    """
    cache_key = (get_current_tenant_id(), user_email)
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
    salesforce_client: Salesforce,
    user_id: str,
    record_ids: list[str],
) -> dict[str, bool]:
    """
    Salesforce has a limit of 200 record ids per query. So we just truncate
    the list of record ids to 200. We only ever retrieve 50 chunks at a time
    so this should be fine (unlikely that we retrieve all 50 chunks contain
    4 unique objects).
    If we decide this isn't acceptable we can use multiple queries but they
    should be in parallel so query time doesn't get too long.
    """
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
