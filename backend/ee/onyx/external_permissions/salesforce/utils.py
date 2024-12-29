from simple_salesforce import Salesforce
from sqlalchemy.orm import Session

from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.document import get_cc_pairs_for_document

_ANY_SALESFORCE_CLIENT: Salesforce | None = None


def get_any_salesforce_client_for_doc_id(
    db_session: Session, doc_id: str
) -> Salesforce:
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


_CC_PAIR_ID_SALESFORCE_CLIENT_MAP: dict[int, Salesforce] = {}
_DOC_ID_TO_CC_PAIR_ID_MAP: dict[str, int] = {}


def get_salesforce_client_for_doc_id(db_session: Session, doc_id: str) -> Salesforce:
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


_SALESFORCE_EMAIL_TO_ID_MAP: dict[str, str] = {}


def get_salesforce_user_id(salesforce_client: Salesforce, user_email: str) -> str:
    if user_email not in _SALESFORCE_EMAIL_TO_ID_MAP:
        query = f"SELECT Id FROM User WHERE Email = '{user_email}'"
        result = salesforce_client.query(query)
        user_id = result["records"][0]["Id"] if result["records"] else None
        _SALESFORCE_EMAIL_TO_ID_MAP[user_email] = user_id
    return _SALESFORCE_EMAIL_TO_ID_MAP[user_email]


def get_objects_access_for_user_id(
    salesforce_client: Salesforce,
    user_id: str,
    record_ids: list[str],
) -> dict[str, bool]:
    record_ids_str = "'" + "','".join(record_ids) + "'"
    access_query = f"""
    SELECT RecordId, HasReadAccess
    FROM UserRecordAccess
    WHERE RecordId IN ({record_ids_str})
    AND UserId = '{user_id}'
    """
    result = salesforce_client.query_all(access_query)
    return {record["RecordId"]: record["HasReadAccess"] for record in result["records"]}
