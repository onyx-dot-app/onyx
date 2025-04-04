from simple_salesforce import Salesforce
from sqlalchemy.orm import Session

from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.document import get_cc_pairs_for_document
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ANY_SALESFORCE_CLIENT: Salesforce | None = None


def get_any_salesforce_client_for_doc_id(
    db_session: Session, doc_id: str
) -> Salesforce:
    """
    We create a salesforce client for the first cc_pair for the first doc_id where
    salesforce censoring is enabled. After that we just cache and reuse the same
    client for all queries.

    We do this to reduce the number of postgres queries we make at query time.

    This may be problematic if they are using multiple cc_pairs for salesforce.
    E.g. there are 2 different credential sets for 2 different salesforce cc_pairs
    but only one has the permissions to access the permissions needed for the query.
    """

    # NOTE: this global seems very very bad
    global _ANY_SALESFORCE_CLIENT
    if _ANY_SALESFORCE_CLIENT is None:
        cc_pairs = get_cc_pairs_for_document(db_session, doc_id)
        first_cc_pair = cc_pairs[0]
        credential_json = first_cc_pair.credential.credential_json
        _ANY_SALESFORCE_CLIENT = Salesforce(
            username=credential_json["sf_username"],
            password=credential_json["sf_password"],
            security_token=credential_json["sf_security_token"],
        )
    return _ANY_SALESFORCE_CLIENT


def _query_salesforce_user_id(sf_client: Salesforce, user_email: str) -> str | None:
    query = f"SELECT Id FROM User WHERE Username = '{user_email}' AND IsActive = true"
    result = sf_client.query(query)
    if len(result["records"]) > 0:
        return result["records"][0]["Id"]

    # try emails
    query = f"SELECT Id FROM User WHERE Email = '{user_email}' AND IsActive = true"
    result = sf_client.query(query)
    if len(result["records"]) > 0:
        return result["records"][0]["Id"]

    return None


# This contains only the user_ids that we have found in Salesforce.
# If we don't know their user_id, we don't store anything in the cache.
_CACHED_SF_EMAIL_TO_ID_MAP: dict[str, str] = {}


def get_salesforce_user_id_from_email(
    sf_client: Salesforce,
    user_email: str,
) -> str | None:
    """
    We cache this so we don't have to query Salesforce for every query and salesforce
    user IDs never change.
    Memory usage is fine because we just store 2 small strings per user.

    If the email is not in the cache, we check the local salesforce database for the info.
    If the user is not found in the local salesforce database, we query Salesforce.
    Whatever we get back from Salesforce is added to the database.
    If no user_id is found, we add a NULL_ID_STRING to the database for that email so
    we don't query Salesforce again (which is slow) but we still check the local salesforce
    database every query until a user id is found. This is acceptable because the query time
    is quite fast.
    If a user_id is created in Salesforce, it will be added to the local salesforce database
    next time the connector is run. Then that value will be found in this function and cached.

    NOTE: First time this runs, it may be slow if it hasn't already been updated in the local
    salesforce database. (Around 0.1-0.3 seconds)
    If it's cached or stored in the local salesforce database, it's fast (<0.001 seconds).
    """

    # NOTE: this global seems bad
    global _CACHED_SF_EMAIL_TO_ID_MAP
    if user_email in _CACHED_SF_EMAIL_TO_ID_MAP:
        if _CACHED_SF_EMAIL_TO_ID_MAP[user_email] is not None:
            return _CACHED_SF_EMAIL_TO_ID_MAP[user_email]

    # some caching via sqlite existed here before ... check history if interested

    # ...query Salesforce and store the result in the database
    user_id = _query_salesforce_user_id(sf_client, user_email)

    if user_id is None:
        return None

    # If the found user_id is real, cache it
    _CACHED_SF_EMAIL_TO_ID_MAP[user_email] = user_id
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
    record_ids_str = "'" + "','".join(truncated_record_ids) + "'"
    access_query = f"""
    SELECT RecordId, HasReadAccess
    FROM UserRecordAccess
    WHERE RecordId IN ({record_ids_str})
    AND UserId = '{user_id}'
    """
    result = salesforce_client.query_all(access_query)
    return {record["RecordId"]: record["HasReadAccess"] for record in result["records"]}


_CC_PAIR_ID_SALESFORCE_CLIENT_MAP: dict[int, Salesforce] = {}
_DOC_ID_TO_CC_PAIR_ID_MAP: dict[str, int] = {}


# NOTE: This is not used anywhere.
def _get_salesforce_client_for_doc_id(db_session: Session, doc_id: str) -> Salesforce:
    """
    Uses a document id to get the cc_pair that indexed that document and uses the credentials
    for that cc_pair to create a Salesforce client.
    Problems:
    - There may be multiple cc_pairs for a document, and we don't know which one to use.
        - right now we just use the first one
    - Building a new Salesforce client for each document is slow.
    - Memory usage could be an issue as we build these dictionaries.
    """
    if doc_id not in _DOC_ID_TO_CC_PAIR_ID_MAP:
        cc_pairs = get_cc_pairs_for_document(db_session, doc_id)
        first_cc_pair = cc_pairs[0]
        _DOC_ID_TO_CC_PAIR_ID_MAP[doc_id] = first_cc_pair.id

    cc_pair_id = _DOC_ID_TO_CC_PAIR_ID_MAP[doc_id]
    if cc_pair_id not in _CC_PAIR_ID_SALESFORCE_CLIENT_MAP:
        cc_pair = get_connector_credential_pair_from_id(
            db_session=db_session,
            cc_pair_id=cc_pair_id,
        )
        if cc_pair is None:
            raise ValueError(f"CC pair {cc_pair_id} not found")
        credential_json = cc_pair.credential.credential_json
        _CC_PAIR_ID_SALESFORCE_CLIENT_MAP[cc_pair_id] = Salesforce(
            username=credential_json["sf_username"],
            password=credential_json["sf_password"],
            security_token=credential_json["sf_security_token"],
        )

    return _CC_PAIR_ID_SALESFORCE_CLIENT_MAP[cc_pair_id]
