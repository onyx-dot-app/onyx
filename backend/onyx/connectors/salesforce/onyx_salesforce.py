import time
from typing import Any

from simple_salesforce import Salesforce
from simple_salesforce import SFType
from simple_salesforce.exceptions import SalesforceRefusedRequest

from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rate_limit_builder,
)
from onyx.connectors.salesforce.blacklist import SALESFORCE_BLACKLISTED_OBJECTS
from onyx.connectors.salesforce.blacklist import SALESFORCE_BLACKLISTED_PREFIXES
from onyx.connectors.salesforce.blacklist import SALESFORCE_BLACKLISTED_SUFFIXES
from onyx.connectors.salesforce.salesforce_calls import get_object_by_id_query
from onyx.connectors.salesforce.utils import ID_FIELD
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder


logger = setup_logger()


def is_salesforce_rate_limit_error(exception: Exception) -> bool:
    """Check if an exception is a Salesforce rate limit error."""
    return isinstance(
        exception, SalesforceRefusedRequest
    ) and "REQUEST_LIMIT_EXCEEDED" in str(exception)


class OnyxSalesforce(Salesforce):
    SOQL_MAX_SUBQUERIES = 20

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self.parent_types: set[str] = set()
        self.child_types: set[str] = set()
        self.parent_to_child_types: dict[str, set[str]] = (
            {}
        )  # map from parent to child types
        self.child_to_parent_types: dict[str, set[str]] = (
            {}
        )  # map from child to parent types
        self.parent_reference_fields_by_type: dict[str, dict[str, list[str]]] = {}
        self.queryable_fields_by_type: dict[str, list[str]] = {}
        self.prefix_to_type: dict[str, str] = (
            {}
        )  # infer the object type of an id immediately

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
                    f"Salesforce rate limit exceeded for query: {query[:100]}..."
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
                    f"Salesforce rate limit exceeded for query_all: {query[:100]}..."
                )
                # Add additional delay for rate limit errors
                time.sleep(5)
            raise

    @staticmethod
    def _make_child_objects_by_id_query(
        object_id: str,
        sf_type: str,
        child_relationships: list[str],
        relationships_to_fields: dict[str, set[str]],
    ) -> str:
        """Returns a SOQL query given the object id, type and child relationships.

        object_id: the id of the parent object
        sf_type: the object name/type of the parent object
        child_relationships: a list of the child object names/types to retrieve
        relationships_to_fields: a mapping of objects to their queryable fields

        When the query is executed, it comes back as result.records[0][child_relationship]
        """

        # supposedly the real limit is 200? But we limit to 10 for practical reasons
        SUBQUERY_LIMIT = 10

        query = "SELECT "
        for child_relationship in child_relationships:
            # TODO(rkuo): what happens if there is a very large list of child records?
            # is that possible problem?

            # NOTE: we actually have to list out the subqueries we want.
            # We can't use the following shortcuts:
            #   FIELDS(ALL) can include binary fields, so don't use that
            #   FIELDS(CUSTOM) can include aggregate queries, so don't use that
            fields = relationships_to_fields[child_relationship]
            fields_fragment = ",".join(fields)
            query += f"(SELECT {fields_fragment} FROM {child_relationship} LIMIT {SUBQUERY_LIMIT}), "

        query = query.rstrip(", ")
        query += f" FROM {sf_type} WHERE Id = '{object_id}'"
        return query

    def query_object(
        self,
        object_type: str,
        object_id: str,
        type_to_queryable_fields: dict[str, set[str]],
    ) -> dict[str, Any] | None:
        record: dict[str, Any] = {}

        queryable_fields = type_to_queryable_fields[object_type]
        query = get_object_by_id_query(object_id, object_type, queryable_fields)
        result = self.safe_query(query)
        if not result:
            return None

        record_0 = result["records"][0]
        for record_key, record_value in record_0.items():
            if record_key == "attributes":
                continue

            record[record_key] = record_value

        return record

    def get_child_objects_by_id(
        self,
        object_id: str,
        sf_type: str,
        child_relationships: list[str],
        relationships_to_fields: dict[str, set[str]],
    ) -> dict[str, dict[str, Any]]:
        """There's a limit on the number of subqueries we can put in a single query."""
        child_records: dict[str, dict[str, Any]] = {}
        child_relationships_batch: list[str] = []
        remaining_child_relationships = list(child_relationships)

        while True:
            process_batch = False

            if (
                len(remaining_child_relationships) == 0
                and len(child_relationships_batch) == 0
            ):
                break

            if len(child_relationships_batch) >= OnyxSalesforce.SOQL_MAX_SUBQUERIES:
                process_batch = True

            if len(remaining_child_relationships) == 0:
                process_batch = True

            if process_batch:
                if len(child_relationships_batch) == 0:
                    break

                query = OnyxSalesforce._make_child_objects_by_id_query(
                    object_id,
                    sf_type,
                    child_relationships_batch,
                    relationships_to_fields,
                )

                try:
                    result = self.safe_query(query)
                except Exception:
                    logger.exception(f"Query failed: {query=}")
                else:
                    for child_record_key, child_result in result["records"][0].items():
                        if child_record_key == "attributes":
                            continue

                        if not child_result:
                            continue

                        for child_record in child_result["records"]:
                            child_record_id = child_record[ID_FIELD]
                            if not child_record_id:
                                logger.warning("Child record has no id")
                                continue

                            child_records[f"{child_record_key}:{child_record_id}"] = (
                                child_record
                            )
                finally:
                    child_relationships_batch.clear()

                continue

            if len(remaining_child_relationships) == 0:
                break

            child_relationship = remaining_child_relationships.pop(0)

            # this is binary content, skip it
            if child_relationship == "Attachments":
                continue

            child_relationships_batch.append(child_relationship)

        return child_records

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
                    f"Salesforce rate limit exceeded for describe_type: {name}"
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
                    f"{index}/{len_relationships} - Invalid child object: "
                    f"parent={sf_type} child={child_name} child_field_backreference={child_relationship['field']} {reason=}"
                )
                continue

            logger.debug(
                f"{index}/{len_relationships} - Found valid child object: "
                f"parent={sf_type} child={child_name} child_field_backreference={child_relationship['field']}"
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
