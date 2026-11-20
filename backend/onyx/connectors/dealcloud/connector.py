from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

from pydantic import JsonValue

from onyx.configs.constants import DocumentSource
from onyx.connectors.dealcloud.models import (
    ENTRY_LIST_TYPE_ATTACHMENT,
    FIELD_TYPE_BINARY,
    FIELD_TYPE_DATA_SOURCE,
    FIELD_TYPE_ENTRY_LIST_ID,
    FIELD_TYPE_IMAGE,
    SYSTEM_FIELD_CREATED,
    SYSTEM_FIELD_CREATED_BY,
    SYSTEM_FIELD_MODIFIED,
    SYSTEM_FIELD_NAME,
    DealCloudCheckpoint,
    DealCloudEntryType,
    DealCloudField,
    DealCloudObjectWalk,
    DealCloudRow,
)
from onyx.connectors.dealcloud.source_operations import (
    ROW_BATCH_SIZE,
    DealCloudApiError,
    DealCloudSourceOperations,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.db.enums import HierarchyNodeType
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

# Row queries in flight at once. DealCloud allows 5 data calls per second, and
# the gateway paces them, so more workers would only wait.
_ROW_FETCH_WORKERS: int = 5
# Entries read per load_from_checkpoint call: one round of parallel row
# queries, so a crash repeats at most one round.
_ENTRIES_PER_STEP: int = _ROW_FETCH_WORKERS * ROW_BATCH_SIZE
_SLIM_BATCH_SIZE: int = 1000
# DealCloud keeps 6 months of change history. 150 days leaves a margin, and
# an older start reads every entry.
_MAX_HISTORY_AGE: timedelta = timedelta(days=150)
_UNINDEXED_FIELD_TYPES: frozenset[int] = frozenset(
    {
        FIELD_TYPE_BINARY,
        FIELD_TYPE_ENTRY_LIST_ID,
        FIELD_TYPE_IMAGE,
        FIELD_TYPE_DATA_SOURCE,
    }
)
_MAILTO_PREFIX: str = "mailto:"


def missing_entry_types(
    entry_types: list[DealCloudEntryType], names: list[str]
) -> list[str]:
    readable: set[str] = {entry_type.api_name.lower() for entry_type in entry_types}
    return sorted(name for name in names if name.lower() not in readable)


def entry_types_not_found(missing: list[str]) -> ConnectorValidationError:
    return ConnectorValidationError(
        f"DealCloud objects not found: {', '.join(missing)}. Check each API "
        "name, or give the API user's group access to the object."
    )


def indexed_entry_types(
    ops: DealCloudSourceOperations, names: list[str]
) -> list[DealCloudEntryType]:
    """The objects in scope: the named ones, or every object except Attachment,
    whose entries are file bytes. A named object DealCloud no longer lists
    leaves the scope. If none of the named objects is listed, the API user
    probably lost access, and a walk would read as every entry being deleted,
    so that raises."""
    entry_types: list[DealCloudEntryType] = ops.list_entry_types()
    if not names:
        return [
            entry_type
            for entry_type in entry_types
            if entry_type.entry_list_type != ENTRY_LIST_TYPE_ATTACHMENT
        ]
    missing: list[str] = missing_entry_types(entry_types, names)
    if len(missing) == len(names):
        raise entry_types_not_found(missing)
    if missing:
        logger.warning(
            "DealCloud no longer lists the objects %s, so they leave the scope.",
            ", ".join(missing),
        )
    wanted: set[str] = {name.lower() for name in names}
    return [
        entry_type
        for entry_type in entry_types
        if entry_type.api_name.lower() in wanted
    ]


def _items(value: JsonValue) -> list[JsonValue]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _item_text(item: JsonValue) -> str | None:
    """A reference, choice or user value shows its name."""
    if isinstance(item, dict):
        name = item.get("name")
        return str(name) if name not in (None, "") else None
    if isinstance(item, bool):
        return "Yes" if item else "No"
    if item is None or item == "":
        return None
    return str(item)


def _value_texts(value: JsonValue) -> list[str]:
    return [text for item in _items(value) if (text := _item_text(item)) is not None]


def _value_url(value: JsonValue) -> str | None:
    for item in _items(value):
        if isinstance(item, dict) and isinstance(url := item.get("url"), str) and url:
            return url
    return None


def _value_time(value: JsonValue) -> datetime | None:
    for item in _items(value):
        if not isinstance(item, str):
            continue
        try:
            moment = datetime.fromisoformat(item)
        except ValueError:
            return None
        # DealCloud gives UTC, with or without the Z.
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return None


def _value_experts(value: JsonValue) -> list[BasicExpertInfo]:
    experts: list[BasicExpertInfo] = []
    for item in _items(value):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        url = item.get("url")
        email = (
            url.removeprefix(_MAILTO_PREFIX)
            if isinstance(url, str) and url.startswith(_MAILTO_PREFIX)
            else None
        )
        if name or email:
            experts.append(
                BasicExpertInfo(display_name=str(name) if name else None, email=email)
            )
    return experts


class DealCloudConnector(
    CheckpointedConnector[DealCloudCheckpoint],
    SlimConnector,
    CredentialsConnector,
):
    def __init__(
        self,
        base_url: str,
        entry_types: list[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.entry_types: list[str] = entry_types or []
        self._ops: DealCloudSourceOperations | None = None
        self._scope: list[DealCloudEntryType] | None = None
        self._walk: DealCloudObjectWalk | None = None

    @property
    def ops(self) -> DealCloudSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("DealCloud")
        return self._ops

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Use set_credentials_provider with this connector.")

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._ops = DealCloudSourceOperations(
            credentials_provider=credentials_provider,
            connector_specific_config={"base_url": self.base_url},
        )

    def validate_connector_settings(self) -> None:
        """Runs before each indexing run, so it accepts what the run accepts:
        a named object that is gone leaves the scope. The form's check is the
        one that names every missing object."""
        try:
            indexed_entry_types(self.ops, self.entry_types)
        except DealCloudApiError as e:
            raise UnexpectedValidationError(str(e)) from e

    def doc_id(self, entry_type_id: int, entry_id: int) -> str:
        """Entry ids repeat across DealCloud sites, so the id carries the site."""
        return f"{self.base_url}/entries/{entry_type_id}/{entry_id}"

    def entry_type_node_id(self, entry_type_id: int) -> str:
        return f"{self.base_url}/entrytypes/{entry_type_id}"

    def _entry_type_node(self, entry_type: DealCloudEntryType) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=self.entry_type_node_id(entry_type.id),
            raw_parent_id=None,
            display_name=entry_type.plural_name,
            link=self.base_url,
            node_type=HierarchyNodeType.FOLDER,
        )

    def _to_document(
        self,
        entry_type: DealCloudEntryType,
        fields: list[DealCloudField],
        row: DealCloudRow,
    ) -> Document:
        title: str | None = None
        link: str | None = None
        updated_at: datetime | None = None
        created_at: datetime | None = None
        owners: list[BasicExpertInfo] = []
        lines: list[str] = []
        for field in fields:
            value: JsonValue = row.values.get(field.api_name)
            if field.system_field_type == SYSTEM_FIELD_NAME:
                # The name is a reference to the entry itself, with its URL.
                title = ", ".join(_value_texts(value)) or None
                link = _value_url(value)
                continue
            if field.system_field_type == SYSTEM_FIELD_MODIFIED:
                updated_at = _value_time(value)
                continue
            if field.system_field_type == SYSTEM_FIELD_CREATED:
                created_at = _value_time(value)
                continue
            if field.system_field_type == SYSTEM_FIELD_CREATED_BY:
                # No continue: the creator is also a line of the text.
                owners = _value_experts(value)
            if field.field_type in _UNINDEXED_FIELD_TYPES:
                continue
            if texts := _value_texts(value):
                lines.append(f"{field.name}: {', '.join(texts)}")
        title = title or f"{entry_type.api_name} {row.entry_id}"
        return Document(
            id=self.doc_id(entry_type.id, row.entry_id),
            sections=[
                TextSection(link=link or self.base_url, text="\n".join(lines) or title)
            ],
            source=DocumentSource.DEALCLOUD,
            semantic_identifier=title,
            title=title,
            doc_updated_at=updated_at,
            doc_created_at=created_at,
            primary_owners=owners or None,
            metadata={"object": entry_type.plural_name},
            parent_hierarchy_raw_node_id=self.entry_type_node_id(entry_type.id),
        )

    def _object_walk(
        self, entry_type: DealCloudEntryType, start: SecondsSinceUnixEpoch
    ) -> DealCloudObjectWalk:
        """Lists the object's entries once per run: those changed since
        `start`, or every entry when `start` is older than DealCloud's change
        history."""
        if self._walk is not None and self._walk.entry_type_id == entry_type.id:
            return self._walk
        since = datetime.fromtimestamp(start, tz=timezone.utc)
        is_full: bool = datetime.now(timezone.utc) - since > _MAX_HISTORY_AGE
        entry_ids: list[int] = (
            self.ops.list_entry_ids(entry_type_id=entry_type.id)
            if is_full
            else self.ops.list_changed_entry_ids(
                entry_type_id=entry_type.id, modified_since=since
            )
        )
        self._walk = DealCloudObjectWalk(
            entry_type_id=entry_type.id,
            fields=self.ops.list_fields(entry_type_id=entry_type.id)
            if entry_ids
            else [],
            entry_ids=entry_ids,
            is_full=is_full,
        )
        return self._walk

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: DealCloudCheckpoint,
    ) -> CheckpointOutput[DealCloudCheckpoint]:
        checkpoint = checkpoint.model_copy(deep=True)
        # Listed once per run, so an object removed since the last run is
        # skipped instead of failing every retry.
        if self._scope is None:
            self._scope = indexed_entry_types(self.ops, self.entry_types)
        active: dict[int, DealCloudEntryType] = {
            entry_type.id: entry_type for entry_type in self._scope
        }
        if checkpoint.entry_type_ids is None:
            checkpoint.entry_type_ids = list(active)
        while checkpoint.entry_type_ids and checkpoint.entry_type_ids[0] not in active:
            checkpoint.entry_type_ids.pop(0)
            checkpoint.last_entry_id = None
        if not checkpoint.entry_type_ids:
            checkpoint.has_more = False
            return checkpoint

        entry_type: DealCloudEntryType = active[checkpoint.entry_type_ids[0]]
        if checkpoint.last_entry_id is None:
            yield self._entry_type_node(entry_type)
        walk: DealCloudObjectWalk = self._object_walk(entry_type, start)
        position: int = bisect_right(walk.entry_ids, checkpoint.last_entry_id or 0)
        step: list[int] = walk.entry_ids[position : position + _ENTRIES_PER_STEP]
        if step:
            batches: list[list[DealCloudRow]] = run_functions_tuples_in_parallel(
                [
                    (
                        partial(
                            self.ops.get_rows,
                            entry_type_id=entry_type.id,
                            entry_ids=step[offset : offset + ROW_BATCH_SIZE],
                        ),
                        (),
                    )
                    for offset in range(0, len(step), ROW_BATCH_SIZE)
                ],
                max_workers=_ROW_FETCH_WORKERS,
            )
            if not any(batches):
                # A query that matches nothing would otherwise index nothing
                # and still report success. The retry lists the entries again.
                raise RuntimeError(
                    f"DealCloud returned no rows for {len(step)} listed "
                    f"{entry_type.api_name} entries"
                )
            # The lower bound is the admin's index start date on a first run.
            # The change history is by commit time, and its entries can have an
            # older modified date, so only a full walk applies it.
            earliest: datetime | None = (
                datetime.fromtimestamp(start, tz=timezone.utc)
                if walk.is_full and start > 0
                else None
            )
            # An entry modified after `end` belongs to a later run.
            latest: datetime = datetime.fromtimestamp(end, tz=timezone.utc)
            for batch in batches:
                for row in batch:
                    document = self._to_document(entry_type, walk.fields, row)
                    updated_at: datetime | None = document.doc_updated_at
                    if updated_at is not None and (
                        (earliest is not None and updated_at < earliest)
                        or updated_at > latest
                    ):
                        continue
                    yield document
            checkpoint.last_entry_id = step[-1]
        if position + len(step) >= len(walk.entry_ids):
            checkpoint.entry_type_ids.pop(0)
            checkpoint.last_entry_id = None
            self._walk = None
        checkpoint.has_more = bool(checkpoint.entry_type_ids)
        return checkpoint

    def build_dummy_checkpoint(self) -> DealCloudCheckpoint:
        return DealCloudCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> DealCloudCheckpoint:
        return DealCloudCheckpoint.model_validate_json(checkpoint_json)

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        for entry_type in indexed_entry_types(self.ops, self.entry_types):
            # A partial walk would read as deleted entries, so stopping raises.
            if callback is not None and callback.should_stop():
                raise RuntimeError("DealCloud slim retrieval: stop signal detected")
            # A prune removes each folder the listing leaves out, and with it
            # the parent link of the folder's documents.
            yield [self._entry_type_node(entry_type)]
            entry_ids: list[int] = self.ops.list_entry_ids(entry_type_id=entry_type.id)
            for offset in range(0, len(entry_ids), _SLIM_BATCH_SIZE):
                yield [
                    SlimDocument(
                        id=self.doc_id(entry_type.id, entry_id),
                        parent_hierarchy_raw_node_id=self.entry_type_node_id(
                            entry_type.id
                        ),
                    )
                    for entry_id in entry_ids[offset : offset + _SLIM_BATCH_SIZE]
                ]
            if callback is not None:
                callback.progress("dealcloud_slim_docs", len(entry_ids))
