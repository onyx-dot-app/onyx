import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from requests import Response
from requests.adapters import HTTPAdapter
from simple_salesforce import Salesforce, SFType
from simple_salesforce.api import exception_handler
from simple_salesforce.exceptions import SalesforceRefusedRequest
from typing_extensions import override
from urllib3.util.retry import Retry

from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rate_limit_builder
from onyx.connectors.salesforce.blacklist import (
    SALESFORCE_BLACKLISTED_OBJECTS,
    SALESFORCE_BLACKLISTED_PREFIXES,
    SALESFORCE_BLACKLISTED_SUFFIXES,
)
from onyx.connectors.salesforce.models import SalesforceSessionCredentials
from onyx.connectors.salesforce.salesforce_calls import (
    get_object_by_id_queries,
    pinned_child_queries,
    plan_child_queries,
)
from onyx.connectors.salesforce.utils import ID_FIELD
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()

# Reopen pooled GET connections closed during long local CSV processing.
_SF_RETRY_TOTAL = 5
_SF_RETRY_BACKOFF_FACTOR = 1.0
_SF_RETRY_STATUS_FORCELIST = (500, 502, 503, 504)
_SALESFORCE_ERROR_CODE_FIELD = "errorCode"
_INVALID_SESSION_ERROR_CODE = "INVALID_SESSION_ID"


def _salesforce_error_code(response: Response) -> str | None:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return None
    if isinstance(payload, dict):
        error_code = payload.get(_SALESFORCE_ERROR_CODE_FIELD)
        return error_code if isinstance(error_code, str) else None
    if not isinstance(payload, list) or not payload:
        return None
    first_error = payload[0]
    if not isinstance(first_error, dict):
        return None
    error_code = first_error.get(_SALESFORCE_ERROR_CODE_FIELD)
    return error_code if isinstance(error_code, str) else None


def is_salesforce_rate_limit_error(exception: Exception) -> bool:
    """Check if an exception is a Salesforce rate limit error."""
    return isinstance(
        exception, SalesforceRefusedRequest
    ) and "REQUEST_LIMIT_EXCEEDED" in str(exception)


class OnyxSalesforce(Salesforce):
    def __init__(
        self,
        *args: Any,
        refresh_callback: Callable[[str], SalesforceSessionCredentials] | None = None,
        **kwargs: Any,
    ) -> None:
        self._oauth_refresh_callback = refresh_callback
        super().__init__(*args, **kwargs)

        self._mount_retry_adapter()

        self.parent_types: set[str] = set()
        self.child_types: set[str] = set()
        self.parent_to_child_types: dict[
            str, set[str]
        ] = {}  # map from parent to child types
        self.child_to_parent_types: dict[
            str, set[str]
        ] = {}  # map from child to parent types
        self.parent_reference_fields_by_type: dict[str, dict[str, list[str]]] = {}
        self.queryable_fields_by_type: dict[str, list[str]] = {}
        self.prefix_to_type: dict[
            str, str
        ] = {}  # infer the object type of an id immediately

    def _set_instance_urls(self) -> None:
        self.base_url = f"https://{self.sf_instance}/services/data/v{self.sf_version}/"
        self.apex_url = f"https://{self.sf_instance}/services/apexrest/"
        self.bulk_url = f"https://{self.sf_instance}/services/async/{self.sf_version}/"
        self.bulk2_url = (
            f"https://{self.sf_instance}/services/data/v{self.sf_version}/jobs/"
        )
        self.metadata_url = (
            f"https://{self.sf_instance}/services/Soap/m/{self.sf_version}/"
        )
        self.tooling_url = f"{self.base_url}tooling/"
        self.oauth2_url = f"https://{self.sf_instance}/services/oauth2/"

    def refresh_session(self) -> None:
        if self._oauth_refresh_callback is None:
            self._refresh_session()
            return
        refreshed = self._oauth_refresh_callback(self.session_id)
        self.session_id = refreshed.sf_access_token
        self.sf_instance = refreshed.sf_instance_host
        self._generate_headers()
        self._set_instance_urls()

    @override
    def _call_salesforce(
        self,
        method: str,
        url: str,
        name: str = "",
        retries: int = 0,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> Response:
        if self._oauth_refresh_callback is None:
            return super()._call_salesforce(
                method, url, name, retries, max_retries, **kwargs
            )

        headers = self.headers.copy()
        headers.update(kwargs.pop("headers", {}))
        result = self.session.request(method, url, headers=headers, **kwargs)

        if (
            result.status_code == 401
            and _salesforce_error_code(result) == _INVALID_SESSION_ERROR_CODE
        ):
            if retries >= max_retries:
                exception_handler(result, name=name)
            previous_host = self.sf_instance
            self.refresh_session()
            parsed_url = urlsplit(url)
            if parsed_url.hostname == previous_host:
                url = urlunsplit(parsed_url._replace(netloc=self.sf_instance))
            return self._call_salesforce(
                method,
                url,
                name,
                retries=retries + 1,
                max_retries=max_retries,
                **kwargs,
            )

        if result.status_code >= 300:
            exception_handler(result, name=name)

        if sforce_limit_info := result.headers.get("Sforce-Limit-Info"):
            self.api_usage = self.parse_api_usage(sforce_limit_info)
        return result

    def _mount_retry_adapter(self) -> None:
        """Retry idempotent requests after stale connections or transient 5xx errors."""
        retry = Retry(
            total=_SF_RETRY_TOTAL,
            connect=_SF_RETRY_TOTAL,
            read=_SF_RETRY_TOTAL,
            status=_SF_RETRY_TOTAL,
            backoff_factor=_SF_RETRY_BACKOFF_FACTOR,
            status_forcelist=_SF_RETRY_STATUS_FORCELIST,
            # urllib3 defaults to idempotent methods; let the SDK raise final errors.
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def initialize(self) -> bool:
        """Eventually cache all first run client state with this method"""
        return True

    def is_blacklisted(self, object_type: str) -> bool:
        """Returns True if the object type is blacklisted."""
        object_type_lower = object_type.lower()
        if object_type_lower in SALESFORCE_BLACKLISTED_OBJECTS:
            return True
        for prefix in SALESFORCE_BLACKLISTED_PREFIXES:
            if object_type_lower.startswith(prefix):
                return True

        for suffix in SALESFORCE_BLACKLISTED_SUFFIXES:
            if object_type_lower.endswith(suffix):
                return True

        return False

    @retry_builder(
        tries=6,
        delay=20,
        backoff=1.5,
        max_delay=60,
        exceptions=(SalesforceRefusedRequest,),
    )
    @rate_limit_builder(max_calls=50, period=60)
    def safe_query(self, query: str, **kwargs: Any) -> dict[str, Any]:
        """Wrapper around the original query method with retry logic and rate limiting."""
        try:
            return super().query(query, **kwargs)
        except SalesforceRefusedRequest as e:
            if is_salesforce_rate_limit_error(e):
                logger.warning(
                    "Salesforce rate limit exceeded for query: %s...", query[:100]
                )
                # Add additional delay for rate limit errors
                time.sleep(5)
            raise

    @retry_builder(
        tries=5,
        delay=20,
        backoff=1.5,
        max_delay=60,
        exceptions=(SalesforceRefusedRequest,),
    )
    @rate_limit_builder(max_calls=50, period=60)
    def safe_query_all(self, query: str, **kwargs: Any) -> dict[str, Any]:
        """Wrapper around the original query_all method with retry logic and rate limiting."""
        try:
            return super().query_all(query, **kwargs)
        except SalesforceRefusedRequest as e:
            if is_salesforce_rate_limit_error(e):
                logger.warning(
                    "Salesforce rate limit exceeded for query_all: %s...", query[:100]
                )
                # Add additional delay for rate limit errors
                time.sleep(5)
            raise

    def query_object(
        self,
        object_type: str,
        object_id: str,
        type_to_queryable_fields: dict[str, set[str]],
    ) -> dict[str, Any] | None:
        queryable_fields = type_to_queryable_fields[object_type]
        if not queryable_fields:
            logger.warning(
                "%s has no queryable fields, skipping %s", object_type, object_id
            )
            return None

        record: dict[str, Any] = {}
        for query in get_object_by_id_queries(object_id, object_type, queryable_fields):
            result = self.safe_query(query)
            if not result["records"]:
                # no rows means the record was deleted or is not visible to this user
                return None

            record.update(
                {k: v for k, v in result["records"][0].items() if k != "attributes"}
            )

        return record

    def get_child_objects_by_id(
        self,
        object_id: str,
        sf_type: str,
        child_relationships: list[str],
        relationships_to_fields: dict[str, set[str]],
    ) -> dict[str, dict[str, Any]]:
        child_records: dict[str, dict[str, Any]] = {}
        chunks_seen: dict[str, int] = {}
        ids_by_relationship: dict[str, list[str]] = {}

        # Attachments hold binary content, skip them
        relationships = [r for r in child_relationships if r != "Attachments"]
        plan = plan_child_queries(
            object_id, sf_type, relationships, relationships_to_fields
        )
        for query in plan.window_queries:
            for relationship, child_id in self._merge_child_rows(
                query, child_records, chunks_seen
            ):
                ids_by_relationship.setdefault(relationship, []).append(child_id)

        for query in pinned_child_queries(
            object_id, sf_type, plan.remaining_chunks, ids_by_relationship
        ):
            self._merge_child_rows(query, child_records, chunks_seen)

        # a child deleted between two chunk queries would otherwise index partially
        expected_chunks = {
            relationship: 1 + len(chunks)
            for relationship, chunks in plan.remaining_chunks.items()
        }
        for key, seen in chunks_seen.items():
            if seen < expected_chunks.get(key.split(":", 1)[0], 1):
                logger.warning("Dropping partial child record %s", key)
                del child_records[key]

        return child_records

    def _merge_child_rows(
        self,
        query: str,
        child_records: dict[str, dict[str, Any]],
        chunks_seen: dict[str, int],
    ) -> list[tuple[str, str]]:
        """Runs one child query, merges its rows, returns (relationship, Id) pairs."""
        merged: list[tuple[str, str]] = []
        result = self.safe_query(query)
        if not result["records"]:
            return merged

        for child_record_key, child_result in result["records"][0].items():
            if child_record_key == "attributes" or not child_result:
                continue

            for child_record in child_result["records"]:
                child_record_id = child_record[ID_FIELD]
                if not child_record_id:
                    logger.warning("Child record has no id")
                    continue

                key = f"{child_record_key}:{child_record_id}"
                # field chunks of one relationship merge into one record
                child_records.setdefault(key, {}).update(child_record)
                chunks_seen[key] = chunks_seen.get(key, 0) + 1
                merged.append((child_record_key, child_record_id))

        return merged

    @retry_builder(
        tries=3,
        delay=1,
        backoff=2,
        exceptions=(SalesforceRefusedRequest,),
    )
    def describe_type(self, name: str) -> Any:
        sf_object = SFType(name, self.session_id, self.sf_instance)
        try:
            result = sf_object.describe()
            return result
        except SalesforceRefusedRequest as e:
            if is_salesforce_rate_limit_error(e):
                logger.warning(
                    "Salesforce rate limit exceeded for describe_type: %s", name
                )
                # Add additional delay for rate limit errors
                time.sleep(3)
            raise

    def get_queryable_fields_by_type(self, name: str) -> set[str]:
        object_description = self.describe_type(name)
        if object_description is None:
            return set()

        fields: list[dict[str, Any]] = object_description["fields"]
        valid_fields: set[str] = set()
        field_names_to_remove: set[str] = set()
        for field in fields:
            if compound_field_name := field.get("compoundFieldName"):
                # We do want to get name fields even if they are compound
                if not field.get("nameField"):
                    field_names_to_remove.add(compound_field_name)

            field_name = field.get("name")
            field_type = field.get("type")
            if field_type in ["base64", "blob", "encryptedstring"]:
                continue

            if field_name:
                valid_fields.add(field_name)

        return valid_fields - field_names_to_remove

    def get_children_of_sf_type(self, sf_type: str) -> dict[str, str]:
        """Returns a dict of child object names to relationship names.
        Relationship names (not object names) are used in subqueries!
        """
        names_to_relationships: dict[str, str] = {}

        object_description = self.describe_type(sf_type)

        index = 0
        len_relationships = len(object_description["childRelationships"])
        for child_relationship in object_description["childRelationships"]:
            child_name = child_relationship["childSObject"]

            index += 1
            valid, reason = self._is_valid_child_object(child_relationship)
            if not valid:
                logger.debug(
                    "%s/%s - Invalid child object: parent=%s child=%s child_field_backreference=%s reason=%r",
                    index,
                    len_relationships,
                    sf_type,
                    child_name,
                    child_relationship["field"],
                    reason,
                )
                continue

            logger.debug(
                "%s/%s - Found valid child object: parent=%s child=%s child_field_backreference=%s",
                index,
                len_relationships,
                sf_type,
                child_name,
                child_relationship["field"],
            )

            name = child_name
            relationship = child_relationship["relationshipName"]

            names_to_relationships[name] = relationship

        return names_to_relationships

    def _is_valid_child_object(
        self, child_relationship: dict[str, Any]
    ) -> tuple[bool, str]:
        if not child_relationship["childSObject"]:
            return False, "childSObject is None"

        child_name = child_relationship["childSObject"]

        if self.is_blacklisted(child_name):
            return False, f"{child_name=} is blacklisted."

        if not child_relationship["relationshipName"]:
            return False, f"{child_name=} has no relationshipName."

        object_description = self.describe_type(child_relationship["childSObject"])
        if not object_description["queryable"]:
            return False, f"{child_name=} is not queryable."

        if not child_relationship["field"]:
            return False, f"{child_name=} has no relationship field."

        if child_relationship["field"] == "RelatedToId":
            return False, f"{child_name=} field is RelatedToId and blacklisted."

        return True, ""

    def get_parent_reference_fields(
        self, sf_type: str, parent_types: set[str]
    ) -> dict[str, list[str]]:
        """
        sf_type: the type in which to find parent reference fields
        parent_types: a list of parent reference field types we are actually interested in
        Other parent types will not be returned.

        Given an object type, returns a dict of field names to a list of referenced parent
        object types.
        (Yes, it is possible for a field to reference one of multiple object types,
        although this seems very unlikely.)

        Returns an empty dict if there are no parent reference fields.
        """

        parent_reference_fields: dict[str, list[str]] = {}

        object_description = self.describe_type(sf_type)
        for field in object_description["fields"]:
            if field["type"] == "reference":
                for reference_to in field["referenceTo"]:
                    if reference_to in parent_types:
                        if field["name"] not in parent_reference_fields:
                            parent_reference_fields[field["name"]] = []
                        parent_reference_fields[field["name"]].append(
                            field["referenceTo"]
                        )

        return parent_reference_fields
