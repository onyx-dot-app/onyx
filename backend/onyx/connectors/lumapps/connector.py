from datetime import datetime
from datetime import timezone
from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.lumapps.client import LumAppsClientError
from onyx.connectors.lumapps.client import OnyxLumApps
from onyx.connectors.lumapps.models import LumAppsCheckpoint
from onyx.connectors.lumapps.utils import extract_body_text
from onyx.connectors.lumapps.utils import pick_lang
from onyx.connectors.lumapps.utils import resolve_metadata_labels
from onyx.connectors.lumapps.utils import slugify_family_key
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.datetime import datetime_to_utc
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Fields requested from content/list. Includes `template`/`properties` so the body is
# returned inline (no per-item content/get / N+1).
_CONTENT_FIELDS = (
    "items(id,uid,type,customContentType,canonicalUrl,link,url,title,slug,status,"
    "updatedAt,publicationDate,metadata,instance,authorId,authorDetails(email),"
    "template,properties),cursor,more"
)
# Must request every field the indexing path can use as the document id
# (id with uid fallback) — anything indexed but missing from the slim set
# would be wrongly pruned.
_SLIM_FIELDS = "items(id,uid,status),cursor,more"
_SLIM_PAGE_SIZE = 100

# Only published content is ingested. The API-side `status` filter in
# `_list_body` is not trusted on its own — enforce LIVE per item too, on both
# the indexing and the pruning path (so content leaving LIVE gets pruned).
_LIVE_STATUS = "LIVE"


def _is_live(content: dict[str, Any]) -> bool:
    return str(content.get("status") or "").upper() == _LIVE_STATUS


def _epoch_to_dt(epoch: float) -> datetime | None:
    # Values too large to be plausible seconds (>1e11 ≈ year 5138) are milliseconds.
    if epoch > 1e11:
        epoch /= 1000.0
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    # LumApps returns ISO-8601 timestamps in practice, but tolerate numeric epochs
    # (seconds or milliseconds) as well: an unparseable value would silently disable
    # the incremental early-break and force a full re-scan on every run.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _epoch_to_dt(float(value))
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return _epoch_to_dt(float(value))
        except ValueError:
            return None
    return datetime_to_utc(parsed)


class LumAppsConnector(CheckpointedConnector[LumAppsCheckpoint], SlimConnector):
    """Ingests LumApps content (pages/news/custom) into Onyx.

    Carries over **all** LumApps metadata families as Onyx metadata
    (``{family_key: [labels]}``), so whatever HR tags — country or otherwise — becomes a
    filterable tag without any connector change.

    Permissions: this is a public-only connector — every piece of LIVE content the
    service user can read is indexed with no per-document access controls, so it is
    visible to all Onyx users regardless of the original LumApps audience. It is not a
    ``CheckpointedConnectorWithPermSync`` and has no entry in the EE permission-sync
    registry. Scope the service user (and optionally ``instance_ids``) to only content
    that is safe to expose org-wide.
    """

    def __init__(
        self,
        base_url: str,
        organization_id: str,
        instance_ids: list[str] | None = None,
        custom_content_types: list[str] | None = None,
        lang: str = "en",
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.base_url = base_url
        self.organization_id = organization_id
        self.instance_ids = instance_ids or None
        self.custom_content_types = custom_content_types or None
        self.lang = lang or "en"
        self.batch_size = min(batch_size, 100)  # LumApps maxResults cap

        self._client: OnyxLumApps | None = None
        self._application_id: str | None = None
        self._api_key: str | None = None
        self._service_user: str | None = None

        # Lazy metadata-label resolution caches (kept on the instance, NOT the checkpoint).
        self._label_map: dict[
            str, tuple[str, str]
        ] = {}  # value id -> (family_key, label)
        self._family_name_cache: dict[str, str] = {}  # family id -> family name

    # ---------------------------------------------------------------- credentials
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._application_id = credentials["lumapps_application_id"]
        self._api_key = credentials["lumapps_api_key"]
        self._service_user = credentials["lumapps_service_user"]
        self._client = None
        return None

    def _get_client(self) -> OnyxLumApps:
        if self._client is not None:
            return self._client
        # The client exchanges the application id + API key via HTTP Basic when
        # minting tokens; over plain http those credentials would travel in
        # cleartext. LumApps is SaaS-only, so https is always available.
        if not self.base_url.lower().startswith("https://"):
            raise ConnectorValidationError(
                "LumApps base URL must use https:// (credentials are sent with "
                "every token request)."
            )
        if not (self._application_id and self._api_key and self._service_user):
            raise ConnectorMissingCredentialError("LumApps")
        self._client = OnyxLumApps(
            base_url=self.base_url,
            organization_id=self.organization_id,
            application_id=self._application_id,
            api_key=self._api_key,
            service_user=self._service_user,
        )
        return self._client

    def validate_connector_settings(self) -> None:
        client = self._get_client()
        try:
            client.list_content(self._list_body(max_results=1, fields="items(id),more"))
        except LumAppsClientError as e:
            if e.status_code == 401:
                raise CredentialExpiredError(
                    "LumApps credentials are invalid or expired."
                )
            if e.status_code == 403:
                raise InsufficientPermissionsError(
                    "The LumApps service user lacks permission to read content."
                )
            raise ConnectorValidationError(str(e))

    # ----------------------------------------------------------------- checkpoint
    def build_dummy_checkpoint(self) -> LumAppsCheckpoint:
        return LumAppsCheckpoint(has_more=True, cursor=None)

    def validate_checkpoint_json(self, checkpoint_json: str) -> LumAppsCheckpoint:
        return LumAppsCheckpoint.model_validate_json(checkpoint_json)

    # ---------------------------------------------------------------- list helper
    def _list_body(
        self,
        cursor: str | None = None,
        fields: str = _CONTENT_FIELDS,
        max_results: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "lang": [self.lang],
            "status": ["LIVE"],
            "sortOrder": ["-updatedAt"],
            "maxResults": max_results or self.batch_size,
            "fields": fields,
        }
        if self.instance_ids:
            body["instanceId"] = self.instance_ids
        if self.custom_content_types:
            body["customContentType"] = self.custom_content_types
        if cursor:
            body["cursor"] = cursor
        return body

    # --------------------------------------------------------------- label resolve
    def _family_name(self, family_id: str, client: OnyxLumApps) -> str:
        if family_id in self._family_name_cache:
            return self._family_name_cache[family_id]
        name = ""
        try:
            name = pick_lang(
                client.get_metadata(family_id, self.lang).get("name"), self.lang
            )
        except LumAppsClientError as e:
            logger.warning(
                "Could not resolve LumApps metadata family %s: %s", family_id, e
            )
        self._family_name_cache[family_id] = name
        return name

    def _resolve_labels(
        self, metadata_ids: list[str], client: OnyxLumApps
    ) -> dict[str, list[str]]:
        for raw_id in metadata_ids:
            metadata_id = str(raw_id)
            if metadata_id in self._label_map:
                continue
            try:
                meta = client.get_metadata(metadata_id, self.lang)
            except LumAppsClientError as e:
                logger.warning(
                    "Could not resolve LumApps metadata id %s: %s", metadata_id, e
                )
                continue
            value_label = pick_lang(meta.get("name"), self.lang)
            family_id = str(meta.get("familyKey") or meta.get("parent") or "")
            family_name = self._family_name(family_id, client) if family_id else ""
            # Non-Latin family names slugify to nothing; fall back to the stable
            # family id so distinct families never collapse into one key.
            fallback_key = f"metadata_{family_id}" if family_id else "metadata"
            self._label_map[metadata_id] = (
                slugify_family_key(family_name, fallback=fallback_key),
                value_label,
            )
        return resolve_metadata_labels(metadata_ids, self._label_map)

    # ---------------------------------------------------------------- to-document
    def _content_to_document(
        self, content: dict[str, Any], client: OnyxLumApps
    ) -> Document:
        content_id = str(content.get("id") or content.get("uid"))
        title = pick_lang(content.get("title"), self.lang) or content_id
        link = (
            pick_lang(content.get("canonicalUrl"), self.lang)
            or content.get("link")
            or content.get("url")
            or ""
        )
        body = extract_body_text(content.get("template"), self.lang)
        if not body:
            body = extract_body_text(content.get("properties"), self.lang)

        metadata: dict[str, str | list[str]] = dict(
            self._resolve_labels(content.get("metadata") or [], client)
        )
        if content.get("type"):
            metadata["content_type"] = str(content["type"])
        if content.get("customContentType"):
            metadata["custom_content_type"] = str(content["customContentType"])

        owners = []
        author_email = (content.get("authorDetails") or {}).get("email")
        if author_email:
            owners = [BasicExpertInfo(email=author_email)]

        return Document(
            id=content_id,
            sections=[TextSection(link=link, text=body)],
            source=DocumentSource.LUMAPPS,
            semantic_identifier=title,
            doc_updated_at=_parse_dt(content.get("updatedAt"))
            or _parse_dt(content.get("publicationDate")),
            primary_owners=owners or None,
            metadata=metadata,
        )

    # --------------------------------------------------------------- checkpointed
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: LumAppsCheckpoint,
    ) -> CheckpointOutput[LumAppsCheckpoint]:
        client = self._get_client()
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)

        response = client.list_content(self._list_body(cursor=checkpoint.cursor))
        items = response.get("items") or []
        next_cursor = response.get("cursor") if response.get("more") else None

        for content in items:
            updated_at = _parse_dt(content.get("updatedAt"))
            # content/list is sorted by -updatedAt, so once we cross below the poll
            # window start there is nothing newer left → stop (incremental early-break).
            if updated_at is not None and updated_at < start_dt:
                return LumAppsCheckpoint(has_more=False, cursor=None)
            # skip anything updated after the window end (newest-first ordering puts
            # these at the top; a failed-attempt retry can use an earlier end).
            if updated_at is not None and updated_at > end_dt:
                continue
            if not _is_live(content):
                logger.debug(
                    "Skipping non-LIVE LumApps content %s (status=%s)",
                    content.get("id") or content.get("uid"),
                    content.get("status"),
                )
                continue
            content_id = str(content.get("id") or content.get("uid"))
            try:
                yield self._content_to_document(content, client)
            except Exception as e:
                logger.exception("Failed to convert LumApps content %s", content_id)
                yield ConnectorFailure(
                    failed_document=DocumentFailure(document_id=content_id),
                    failure_message=str(e),
                    exception=e,
                )

        if next_cursor:
            return LumAppsCheckpoint(has_more=True, cursor=next_cursor)
        return LumAppsCheckpoint(has_more=False, cursor=None)

    # ----------------------------------------------------------------------- slim
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002 (full-state enum)
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        # Enumerate the SAME scope that indexing covers (LIVE content for the configured
        # instances/content-types) so pruning never deletes validly-indexed docs.
        # The client raises on any non-200, so a partial enumeration aborts (never a
        # truncated set) — required for safe pruning.
        client = self._get_client()
        cursor: str | None = None
        while True:
            if callback and callback.should_stop():
                return
            response = client.list_content(
                self._list_body(
                    cursor=cursor, fields=_SLIM_FIELDS, max_results=_SLIM_PAGE_SIZE
                )
            )
            items = response.get("items") or []
            # Same id fallback as _content_to_document — a doc indexed under its
            # uid must appear in the slim set or pruning would delete it.
            batch: list[SlimDocument | HierarchyNode] = [
                SlimDocument(id=str(item.get("id") or item.get("uid")))
                for item in items
                if (item.get("id") or item.get("uid")) and _is_live(item)
            ]
            if batch:
                yield batch
            if callback:
                callback.progress("lumapps_slim", len(batch))
            cursor = response.get("cursor") if response.get("more") else None
            if not cursor:
                return
