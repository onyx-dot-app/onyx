from collections import defaultdict
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, delete, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased

from onyx.configs.constants import DocumentSource
from onyx.db.document_access import apply_document_access_filter
from onyx.db.models import Document, Document__Tag, Tag
from onyx.db.tag_models import DocumentTagInput
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Orphan-tag deletes must stay bounded: a single unbounded DELETE over millions
# of orphans generates one massive transaction (locks + WAL burst) that can
# saturate the primary DB.
ORPHAN_TAG_DELETION_BATCH_SIZE = 5000


def check_tag_validity(tag_key: str, tag_value: str) -> bool:
    """If a tag is too long, it should not be used (it will cause an error in Postgres
    as the unique constraint can only apply to entries that are less than 2704 bytes).

    Additionally, extremely long tags are not really usable / useful."""
    if len(tag_key) + len(tag_value) > 255:
        logger.error(
            "Tag with key '%s' and value '%s' is too long, cannot be used",
            tag_key,
            tag_value,
        )
        return False

    return True


def create_or_add_document_tag(
    tag_key: str,
    tag_value: str,
    source: DocumentSource,
    document_id: str,
    db_session: Session,
) -> Tag | None:
    if not check_tag_validity(tag_key, tag_value):
        return None

    document = db_session.get(Document, document_id)
    if not document:
        raise ValueError("Invalid Document, cannot attach Tags")

    # Use upsert to avoid race condition when multiple workers try to create the same tag
    insert_stmt = pg_insert(Tag).values(
        tag_key=tag_key,
        tag_value=tag_value,
        source=source,
        is_list=False,
    )
    insert_stmt = insert_stmt.on_conflict_do_nothing(
        constraint="_tag_key_value_source_list_uc"
    )
    db_session.execute(insert_stmt)

    # Now fetch the tag (either just inserted or already existed)
    tag_stmt = select(Tag).where(
        Tag.tag_key == tag_key,
        Tag.tag_value == tag_value,
        Tag.source == source,
        Tag.is_list.is_(False),
    )
    tag = db_session.execute(tag_stmt).scalar_one()

    if tag not in document.tags:
        document.tags.append(tag)

    db_session.commit()
    return tag


def create_or_add_document_tag_list(
    tag_key: str,
    tag_values: list[str],
    source: DocumentSource,
    document_id: str,
    db_session: Session,
) -> list[Tag]:
    valid_tag_values = [
        tag_value for tag_value in tag_values if check_tag_validity(tag_key, tag_value)
    ]
    if not valid_tag_values:
        return []

    document = db_session.get(Document, document_id)
    if not document:
        raise ValueError("Invalid Document, cannot attach Tags")

    # Use upsert to avoid race condition when multiple workers try to create the same tags
    for tag_value in valid_tag_values:
        insert_stmt = pg_insert(Tag).values(
            tag_key=tag_key,
            tag_value=tag_value,
            source=source,
            is_list=True,
        )
        insert_stmt = insert_stmt.on_conflict_do_nothing(
            constraint="_tag_key_value_source_list_uc"
        )
        db_session.execute(insert_stmt)

    # Now fetch all tags (either just inserted or already existed)
    all_tags_stmt = select(Tag).where(
        Tag.tag_key == tag_key,
        Tag.tag_value.in_(valid_tag_values),
        Tag.source == source,
        Tag.is_list.is_(True),
    )
    all_tags = list(db_session.execute(all_tags_stmt).scalars().all())

    for tag in all_tags:
        if tag not in document.tags:
            document.tags.append(tag)

    db_session.commit()
    return all_tags


# (tag_key, tag_value, source, is_list): the unique key of a Tag row.
_TagKey = tuple[str, str, DocumentSource, bool]


def _tag_keys_for_metadata(
    source: DocumentSource, metadata: dict[str, str | list[str]]
) -> set[_TagKey]:
    tag_keys: set[_TagKey] = set()
    for key, value in metadata.items():
        if isinstance(value, list):
            tag_keys.update(
                (key, item, source, True)
                for item in value
                if check_tag_validity(key, item)
            )
        elif check_tag_validity(key, value):
            tag_keys.add((key, value, source, False))
    return tag_keys


def _fetch_tag_ids(
    tag_keys: Iterable[_TagKey], db_session: Session
) -> dict[_TagKey, int]:
    keys_by_source: dict[DocumentSource, list[tuple[str, str, bool]]] = defaultdict(
        list
    )
    for tag_key, tag_value, source, is_list in tag_keys:
        keys_by_source[source].append((tag_key, tag_value, is_list))

    tag_ids: dict[_TagKey, int] = {}
    for source, keys in keys_by_source.items():
        stmt = select(Tag.id, Tag.tag_key, Tag.tag_value, Tag.is_list).where(
            Tag.source == source,
            tuple_(Tag.tag_key, Tag.tag_value, Tag.is_list).in_(keys),
        )
        for tag_id, tag_key, tag_value, is_list in db_session.execute(stmt):
            tag_ids[(tag_key, tag_value, source, is_list)] = tag_id
    return tag_ids


def upsert_document_tags_batch(
    documents: list[DocumentTagInput],
    db_session: Session,
) -> None:
    """Makes the tags of each document equal to its metadata, in one
    transaction. Commits.

    Each multi-row write is in key order, so two batches that share tags or
    documents take their row locks in the same order."""
    if not documents:
        return

    all_tag_keys: set[_TagKey] = set()
    # A later entry for the same document wins.
    doc_id_to_tag_keys: dict[str, set[_TagKey]] = {}
    for document in documents:
        tag_keys = _tag_keys_for_metadata(document.source, document.metadata)
        all_tag_keys.update(tag_keys)
        doc_id_to_tag_keys[document.document_id] = tag_keys

    document_ids = sorted(doc_id_to_tag_keys)
    found_document_ids = set(
        db_session.scalars(select(Document.id).where(Document.id.in_(document_ids)))
    )
    if len(found_document_ids) != len(document_ids):
        raise ValueError("Invalid Document, cannot attach Tags")

    tag_ids = _fetch_tag_ids(all_tag_keys, db_session)
    missing_tag_keys = sorted(all_tag_keys - tag_ids.keys())
    if missing_tag_keys:
        # ON CONFLICT waits for a concurrent worker that creates the same tag.
        # No commit here: a tag with no document is open to the orphan cleanup.
        db_session.execute(
            pg_insert(Tag)
            .values(
                [
                    {
                        "tag_key": tag_key,
                        "tag_value": tag_value,
                        "source": source,
                        "is_list": is_list,
                    }
                    for tag_key, tag_value, source, is_list in missing_tag_keys
                ]
            )
            .on_conflict_do_nothing(constraint="_tag_key_value_source_list_uc")
        )
        tag_ids.update(_fetch_tag_ids(missing_tag_keys, db_session))
        if len(tag_ids) != len(all_tag_keys):
            raise RuntimeError("Bug: a tag is missing after its upsert")

    wanted_links: set[tuple[str, int]] = {
        (document_id, tag_ids[tag_key])
        for document_id, tag_keys in doc_id_to_tag_keys.items()
        for tag_key in tag_keys
    }
    current_links: set[tuple[str, int]] = {
        (document_id, tag_id)
        for document_id, tag_id in db_session.execute(
            select(Document__Tag.document_id, Document__Tag.tag_id).where(
                Document__Tag.document_id.in_(document_ids)
            )
        )
    }

    new_links = sorted(wanted_links - current_links)
    if new_links:
        db_session.execute(
            pg_insert(Document__Tag)
            .values(
                [
                    {"document_id": document_id, "tag_id": tag_id}
                    for document_id, tag_id in new_links
                ]
            )
            .on_conflict_do_nothing()
        )

    stale_links = sorted(current_links - wanted_links)
    if stale_links:
        # A DELETE locks rows in scan order. The CTE locks them in key order,
        # and the DELETE removes only the rows it locked.
        locked = (
            select(Document__Tag.document_id, Document__Tag.tag_id)
            .where(
                tuple_(Document__Tag.document_id, Document__Tag.tag_id).in_(stale_links)
            )
            .order_by(Document__Tag.document_id, Document__Tag.tag_id)
            .with_for_update()
            .cte("locked")
        )
        db_session.execute(
            delete(Document__Tag)
            .where(
                Document__Tag.document_id == locked.c.document_id,
                Document__Tag.tag_id == locked.c.tag_id,
            )
            .execution_options(synchronize_session=False)
        )

    db_session.commit()


def find_tags(
    tag_key_prefix: str | None,
    tag_value_prefix: str | None,
    sources: list[DocumentSource] | None,
    limit: int | None,
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    user_id: UUID | None = None,
    # if set, both tag_key_prefix and tag_value_prefix must be a match
    require_both_to_match: bool = False,
    prior_emails: list[str] | None = None,
) -> list[Tag]:
    accessible_documents: Select[tuple[str]] = (
        select(Document.id)
        .join(Document__Tag, Document__Tag.document_id == Document.id)
        .where(Document__Tag.tag_id == Tag.id)
        .correlate(Tag)
    )
    accessible_documents = apply_document_access_filter(
        db_session,
        accessible_documents,
        user_email,
        external_group_ids,
        user_id=user_id,
        prior_emails=prior_emails,
    )
    query = select(Tag).where(accessible_documents.exists())

    if tag_key_prefix or tag_value_prefix:
        conditions = []
        if tag_key_prefix:
            conditions.append(Tag.tag_key.istartswith(tag_key_prefix, autoescape=True))
        if tag_value_prefix:
            conditions.append(
                Tag.tag_value.istartswith(tag_value_prefix, autoescape=True)
            )

        final_prefix_condition = (
            and_(*conditions) if require_both_to_match else or_(*conditions)
        )
        query = query.where(final_prefix_condition)

    if sources:
        query = query.where(Tag.source.in_(sources))

    if limit:
        query = query.limit(limit)

    result = db_session.execute(query)

    tags = result.scalars().all()
    return list(tags)


def get_structured_tags_for_document(
    document_id: str, db_session: Session
) -> dict[str, str | list[str]]:
    """Essentially returns the document metadata from postgres."""
    document = db_session.get(Document, document_id)
    if not document:
        raise ValueError("Invalid Document, cannot find tags")

    document_metadata: dict[str, Any] = {}
    for tag in document.tags:
        if tag.is_list:
            document_metadata.setdefault(tag.tag_key, [])
            # should always be a list (if tag.is_list is always True for this key), but just in case
            if not isinstance(document_metadata[tag.tag_key], list):
                logger.warning(
                    "Inconsistent is_list for document %s, tag_key %s",
                    document_id,
                    tag.tag_key,
                )
                document_metadata[tag.tag_key] = [document_metadata[tag.tag_key]]
            document_metadata[tag.tag_key].append(tag.tag_value)
            continue

        # set value (ignore duplicate keys, though there should be none)
        document_metadata.setdefault(tag.tag_key, tag.tag_value)

        # should always be a value, but just in case (treat it as a list in this case)
        if isinstance(document_metadata[tag.tag_key], list):
            logger.warning(
                "Inconsistent is_list for document %s, tag_key %s",
                document_id,
                tag.tag_key,
            )
            document_metadata[tag.tag_key] = [document_metadata[tag.tag_key]]
    return document_metadata


def delete_document_tags_for_documents__no_commit(
    document_ids: list[str], db_session: Session
) -> None:
    stmt = delete(Document__Tag).where(Document__Tag.document_id.in_(document_ids))
    db_session.execute(stmt)


def _delete_orphan_tags_batch(db_session: Session, batch_size: int) -> int:
    """Deletes at most batch_size orphan tags in a single server-side statement.

    The candidate ids are selected via a LIMITed subquery so no ids are ever
    materialized into Python. Returns the number of tags deleted.
    """
    # Alias Tag so the subquery doesn't auto-correlate against the DELETE target.
    candidate_tag = aliased(Tag)
    orphan_tag_ids = (
        select(candidate_tag.id)
        .where(
            ~select(Document__Tag.tag_id)
            .where(Document__Tag.tag_id == candidate_tag.id)
            .exists()
        )
        .limit(batch_size)
        .scalar_subquery()
    )
    delete_stmt = (
        delete(Tag)
        .where(Tag.id.in_(orphan_tag_ids))
        .execution_options(synchronize_session=False)
    )
    result = db_session.execute(delete_stmt)
    return result.rowcount  # ty: ignore[unresolved-attribute]


def delete_orphan_tags__no_commit(
    db_session: Session,
    batch_size: int = ORPHAN_TAG_DELETION_BATCH_SIZE,
) -> int:
    """Best-effort cleanup of at most one batch of orphan tags inside the
    caller's transaction. Intentionally bounded so callers holding long
    transactions (e.g. connector deletion) don't balloon them; use
    delete_orphan_tags_batched for a full drain."""
    return _delete_orphan_tags_batch(db_session, batch_size)


def delete_orphan_tags_batched(
    db_session: Session,
    batch_size: int = ORPHAN_TAG_DELETION_BATCH_SIZE,
) -> int:
    """Deletes all orphan tags in bounded batches, committing after each batch.

    Only call with no uncommitted work pending on db_session, since each batch
    commits. Returns the total number of tags deleted."""
    total_deleted = 0
    batch_count = 0
    while True:
        num_deleted = _delete_orphan_tags_batch(db_session, batch_size)
        if num_deleted == 0:
            # nothing to persist, but the probe opened a transaction — end it
            # rather than leaving the session idle-in-transaction
            db_session.rollback()
            break
        db_session.commit()
        total_deleted += num_deleted
        batch_count += 1

    if total_deleted:
        logger.info("Deleted %d orphan tags in %d batches", total_deleted, batch_count)
    return total_deleted
