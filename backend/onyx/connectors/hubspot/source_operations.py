"""HubSpot source operations: the one place HubSpot is called. Indexing and
the permission sync compose these operations, so a capability check can probe
the same call production makes. Operations return plain models, never SDK
objects, and every call goes through the shared rate limiter."""

from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from typing import Any, TypeVar

import requests
from hubspot import HubSpot
from hubspot.crm.associations.v4.exceptions import (
    ApiException as AssociationsApiException,
)
from hubspot.crm.companies.exceptions import ApiException as CompaniesApiException
from hubspot.crm.contacts.exceptions import ApiException as ContactsApiException
from hubspot.crm.contacts.models import (
    BatchReadInputSimplePublicObjectId,
    Filter,
    FilterGroup,
    PublicObjectSearchRequest,
    SimplePublicObjectId,
)
from hubspot.crm.deals.exceptions import ApiException as DealsApiException
from hubspot.crm.objects.notes.exceptions import ApiException as NotesApiException
from hubspot.crm.tickets.exceptions import ApiException as TicketsApiException
from pydantic import BaseModel

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.hubspot.config import HUBSPOT_OBJECT_SPECS, HubSpotObjectType
from onyx.connectors.hubspot.models import (
    ApiAssociationPage,
    ApiPaging,
    ApiPermittedUsersResponse,
    ApiPortalInfo,
    ApiRecord,
    ApiRecordPage,
    ApiUsersResponse,
    HubSpotAssociationIds,
    HubSpotPage,
    HubSpotRecord,
    HubSpotUser,
)
from onyx.connectors.hubspot.rate_limit import HubSpotRateLimiter
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

HUBSPOT_API_BASE = "https://api.hubapi.com"
PORTAL_INFO_PATH = "/integrations/v1/me"
USERS_PATH = "/settings/users/2026-09"
PERMITTED_USERS_PATH = "/resource-permissions/v3/permitted-users"
VIEW_ACTION = "crm-object:VIEW"
CREDENTIAL_ACCESS_TOKEN = "hubspot_access_token"

HUBSPOT_PAGE_SIZE = 100
USERS_PAGE_SIZE = 100
# Measured: HubSpot rejects a permitted-users request naming more resources.
PERMITTED_USERS_BATCH_SIZE = 20
# Notes are an engagement, read through their own SDK client.
NOTES_OBJECT_TYPE = "notes"

# Each generated SDK client raises its own ApiException class.
_SDK_API_EXCEPTIONS = (
    AssociationsApiException,
    CompaniesApiException,
    ContactsApiException,
    DealsApiException,
    NotesApiException,
    TicketsApiException,
)
_RECORD_VARIANTS = tuple(object_type.value for object_type in HubSpotObjectType)
_READ_VARIANTS = _RECORD_VARIANTS + (NOTES_OBJECT_TYPE,)
_NOT_YET_PROBED = "No HubSpot capability check composes this operation yet."

_T = TypeVar("_T")
_M = TypeVar("_M", bound=BaseModel)
_ItemT = TypeVar("_ItemT")

QueryParams = dict[str, str | int | list[str]]


class HubSpotApiError(Exception):
    """A refused or failed HubSpot call. Carries the status and headers the
    rate limiter reads, and the operation name for the permission probe's message."""

    def __init__(
        self,
        operation: str,
        status: int | None,
        headers: Mapping[str, str] | None,
        detail: str,
    ) -> None:
        self.operation = operation
        self.status = status
        self.headers = headers
        super().__init__(f"HubSpot returned {status} for {operation}: {detail[:200]}")


def iter_pages(
    fetch: Callable[[str | None], HubSpotPage[_ItemT]], max_pages: int
) -> Iterator[_ItemT]:
    """Walks a cursor listing. A cursor that stops moving or a walk past
    max_pages raises, since a short listing would be taken as complete."""
    after: str | None = None
    for _ in range(max_pages):
        page = fetch(after)
        yield from page.items
        if page.next_after is None:
            return
        if page.next_after == after:
            raise RuntimeError(f"HubSpot listing cursor stopped moving at {after!r}")
        after = page.next_after
    raise RuntimeError(f"HubSpot listing ran past {max_pages} pages")


def _next_after(paging: ApiPaging | None) -> str | None:
    return paging.next.after if paging and paging.next else None


def _utc(moment: datetime) -> datetime:
    # HubSpot sends UTC, so a naive value is UTC too.
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _record(raw: ApiRecord) -> HubSpotRecord:
    associations: dict[str, HubSpotAssociationIds] | None = None
    if raw.associations is not None:
        associations = {
            assoc_type: HubSpotAssociationIds(
                # One entry per association label, so an id can repeat.
                ids=list(dict.fromkeys(item.id for item in collection.results)),
                has_more=_next_after(collection.paging) is not None,
            )
            for assoc_type, collection in raw.associations.items()
        }
    return HubSpotRecord(
        id=raw.id,
        properties=raw.properties or {},
        created_at=_utc(raw.created_at),
        updated_at=_utc(raw.updated_at),
        associations=associations,
    )


def _record_page(page: Any) -> HubSpotPage[HubSpotRecord]:
    raw = ApiRecordPage.model_validate(page.to_dict())
    return HubSpotPage(
        items=[_record(item) for item in raw.results],
        next_after=_next_after(raw.paging),
    )


def _epoch_ms(moment: datetime) -> str:
    return str(int(moment.timestamp() * 1000))


class HubSpotSourceOperations(SourceOperations):
    source = DocumentSource.HUBSPOT
    sdk_modules = ("hubspot", "requests")
    # The gateway reads only the credential. object_types stays in the connector.
    config_keys = frozenset()

    _token: str | None = None
    _client: HubSpot | None = None
    _rate_limiter: HubSpotRateLimiter | None = None

    def _access_token(self) -> str:
        """Read once: a DB-backed provider decrypts and audits on every read."""
        if self._token is None:
            token = self.credentials_provider.get_credentials().get(
                CREDENTIAL_ACCESS_TOKEN
            )
            if not token:
                raise ConnectorMissingCredentialError("HubSpot")
            self._token = str(token)
        return self._token

    def _api(self) -> HubSpot:
        if self._client is None:
            self._client = HubSpot(access_token=self._access_token())
        return self._client

    def _limiter(self) -> HubSpotRateLimiter:
        if self._rate_limiter is None:
            self._rate_limiter = HubSpotRateLimiter()
        return self._rate_limiter

    def _crm(self, variant: str) -> Any:
        """The SDK's per-object client, which it leaves untyped."""
        crm = self._api().crm
        return {
            HubSpotObjectType.TICKETS.value: crm.tickets,
            HubSpotObjectType.COMPANIES.value: crm.companies,
            HubSpotObjectType.DEALS.value: crm.deals,
            HubSpotObjectType.CONTACTS.value: crm.contacts,
            NOTES_OBJECT_TYPE: crm.objects.notes,
        }[variant]

    def _sdk(self, operation: str, func: Callable[..., _T], **kwargs: Any) -> _T:
        """Runs one SDK call under the rate limiter. The SDK sends no timeout
        unless one is passed per call. An SDK refusal becomes a HubSpotApiError
        so callers see one error type for SDK and REST calls."""
        kwargs.setdefault("_request_timeout", REQUEST_TIMEOUT_SECONDS)

        def call() -> _T:
            try:
                return func(**kwargs)
            except _SDK_API_EXCEPTIONS as e:
                raise HubSpotApiError(
                    operation, e.status, e.headers, str(e.body or e.reason or "")
                ) from e

        return self._limiter().call(call)

    def _rest(
        self, operation: str, model: type[_M], path: str, params: QueryParams
    ) -> _M:
        """Runs one REST call the SDK has no client for."""

        def call() -> _M:
            response = requests.get(
                f"{HUBSPOT_API_BASE}{path}",
                headers={"Authorization": f"Bearer {self._access_token()}"},
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code >= 400:
                raise HubSpotApiError(
                    operation, response.status_code, response.headers, response.text
                )
            return model.model_validate(response.json())

        return self._limiter().call(call)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_PROBED,
    )
    def get_portal_id(self) -> str:
        return str(
            self._rest("portal info", ApiPortalInfo, PORTAL_INFO_PATH, {}).portal_id
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        variants=_RECORD_VARIANTS,
        untested=_NOT_YET_PROBED,
    )
    def list_records(
        self,
        *,
        variant: HubSpotObjectType,
        properties: list[str],
        associations: list[HubSpotObjectType] | None = None,
        after: str | None = None,
        limit: int = HUBSPOT_PAGE_SIZE,
    ) -> HubSpotPage[HubSpotRecord]:
        """One page of records. Requested associations come back inline, with
        has_more set when HubSpot paged them."""
        page = self._sdk(
            f"{variant} listing",
            self._crm(variant).basic_api.get_page,
            limit=limit,
            properties=properties,
            associations=[assoc.value for assoc in associations]
            if associations
            else None,
            after=after,
        )
        return _record_page(page)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        variants=_RECORD_VARIANTS,
        untested=_NOT_YET_PROBED,
    )
    def search_records(
        self,
        *,
        variant: HubSpotObjectType,
        properties: list[str],
        modified_after: datetime,
        modified_before: datetime | None,
        after: str | None = None,
        limit: int = HUBSPOT_PAGE_SIZE,
    ) -> HubSpotPage[HubSpotRecord]:
        """One page of records modified in the window, oldest first. The Search
        API takes no associations parameter, so none come back inline."""
        modified_date_property = HUBSPOT_OBJECT_SPECS[variant].modified_date_property
        filters = [
            Filter(
                property_name=modified_date_property,
                operator="GTE",
                value=_epoch_ms(modified_after),
            )
        ]
        if modified_before is not None:
            filters.append(
                Filter(
                    property_name=modified_date_property,
                    operator="LTE",
                    value=_epoch_ms(modified_before),
                )
            )
        # The request body is the same for every object type.
        request = PublicObjectSearchRequest(
            filter_groups=[FilterGroup(filters=filters)],
            limit=limit,
            properties=properties,
            after=after,
            sorts=[modified_date_property],
        )
        page = self._sdk(
            f"{variant} search",
            self._crm(variant).search_api.do_search,
            public_object_search_request=request,
        )
        return _record_page(page)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_PROBED,
    )
    def list_associations(
        self,
        *,
        object_type: HubSpotObjectType,
        object_id: str,
        to_object_type: str,
        after: str | None = None,
        limit: int = HUBSPOT_PAGE_SIZE,
    ) -> HubSpotPage[str]:
        """One page of ids of the records (or notes) linked to one record."""
        page = self._sdk(
            f"{object_type} to {to_object_type} associations",
            self._api().crm.associations.v4.basic_api.get_page,
            object_type=object_type.value,
            object_id=object_id,
            to_object_type=to_object_type,
            limit=limit,
            after=after,
        )
        raw = ApiAssociationPage.model_validate(page.to_dict())
        return HubSpotPage(
            items=[str(item.to_object_id) for item in raw.results],
            next_after=_next_after(raw.paging),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        variants=_READ_VARIANTS,
        untested=_NOT_YET_PROBED,
    )
    def read_records(
        self, *, variant: str, ids: list[str], properties: list[str]
    ) -> list[HubSpotRecord]:
        """Up to a page of records (or notes) by id."""
        if len(ids) > HUBSPOT_PAGE_SIZE:
            raise ValueError(
                f"HubSpot reads at most {HUBSPOT_PAGE_SIZE} records per batch"
            )
        # The request body is the same for every object type.
        request = BatchReadInputSimplePublicObjectId(
            properties=properties,
            inputs=[SimplePublicObjectId(id=record_id) for record_id in ids],
        )
        response = self._sdk(
            f"{variant} batch read",
            self._crm(variant).batch_api.read,
            batch_read_input_simple_public_object_id=request,
        )
        return [
            _record(ApiRecord.model_validate(item.to_dict()))
            for item in response.results or []
        ]

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_PROBED,
    )
    def list_users(
        self, *, after: str | None = None, limit: int = USERS_PAGE_SIZE
    ) -> HubSpotPage[HubSpotUser]:
        params: QueryParams = {"limit": limit}
        if after is not None:
            params["after"] = after
        page = self._rest("user listing", ApiUsersResponse, USERS_PATH, params)
        return HubSpotPage(items=page.results, next_after=_next_after(page.paging))

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_PROBED,
    )
    def get_user(self, *, user_id: int) -> HubSpotUser | None:
        """None when HubSpot no longer knows the id."""
        try:
            return self._rest(
                f"user {user_id}", HubSpotUser, f"{USERS_PATH}/{user_id}", {}
            )
        except HubSpotApiError as e:
            if e.status == 404:
                return None
            raise

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_PROBED,
    )
    def get_record_viewers(
        self, *, portal_id: str, object_type: HubSpotObjectType, record_ids: list[str]
    ) -> dict[str, set[int]]:
        """The user ids allowed to view each record. A record HubSpot gives no
        answer for maps to an empty set."""
        if len(record_ids) > PERMITTED_USERS_BATCH_SIZE:
            raise ValueError(
                f"HubSpot answers for at most {PERMITTED_USERS_BATCH_SIZE} records per call"
            )
        type_id = HUBSPOT_OBJECT_SPECS[object_type].type_id
        hcrns = {
            f"hcrn:{portal_id}:crm-object:{type_id}:{record_id}": record_id
            for record_id in record_ids
        }
        response = self._rest(
            "record viewers",
            ApiPermittedUsersResponse,
            PERMITTED_USERS_PATH,
            {"resource": list(hcrns)},
        )
        viewers: dict[str, set[int]] = {}
        for hcrn, record_id in hcrns.items():
            actions = response.resources.get(hcrn)
            if actions is None:
                logger.warning(
                    "HubSpot gave no viewer list for %s %s, so it stays private",
                    object_type,
                    record_id,
                )
                viewers[record_id] = set()
                continue
            view = actions.get(VIEW_ACTION)
            viewers[record_id] = set(view.permitted_users) if view else set()
        return viewers
