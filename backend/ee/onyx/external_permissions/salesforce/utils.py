from simple_salesforce import Salesforce
from sqlalchemy.orm import Session

from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.document import get_cc_pairs_for_document

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


_SALESFORCE_EMAIL_TO_ID_MAP: dict[str, str] = {}


def get_salesforce_user_id(salesforce_client: Salesforce, user_email: str) -> str:
    """
    We cache this so we don't have to query Salesforce for every query and salesforce
    user IDs never change.
    Memory usage is fine because we just store 2 small strings per user.
    """
    if user_email not in _SALESFORCE_EMAIL_TO_ID_MAP:
        query = f"SELECT Id FROM User WHERE Email = '{user_email}'"
        result = salesforce_client.query(query)
        user_id = result["records"][0]["Id"]
        _SALESFORCE_EMAIL_TO_ID_MAP[user_email] = user_id
    return _SALESFORCE_EMAIL_TO_ID_MAP[user_email]


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
        cc_pair = get_connector_credential_pair_from_id(cc_pair_id, db_session)
        if cc_pair is None:
            raise ValueError(f"CC pair {cc_pair_id} not found")
        credential_json = cc_pair.credential.credential_json
        _CC_PAIR_ID_SALESFORCE_CLIENT_MAP[cc_pair_id] = Salesforce(
            username=credential_json["sf_username"],
            password=credential_json["sf_password"],
            security_token=credential_json["sf_security_token"],
        )

    return _CC_PAIR_ID_SALESFORCE_CLIENT_MAP[cc_pair_id]
