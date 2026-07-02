from collections.abc import Iterator
from contextlib import contextmanager
from typing import BinaryIO
from typing import Final

from sqlalchemy.orm import Session

from onyx.db.models import Skill
from onyx.db.models import User
from onyx.db.skill import replace_skill_bundle
from onyx.db.skill import skill_ids_with_grants
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.built_in import EXTERNAL_APP_BUILT_IN_SKILL_IDS
from onyx.skills.bundle import read_bundle_file
from onyx.skills.bundle import slug_from_filename
from onyx.skills.ingest import delete_bundle_blob
from onyx.skills.ingest import ingested_skill_bundle as ingest_bundle_with_cleanup
from onyx.skills.ingest import IngestedBundle
from onyx.skills.push import push_skill_to_affected_sandboxes

# Built-in slugs plus external-app provider slugs (rows created on demand by
# slug — a user-claimed slug would block the org from connecting that app).
_RESERVED_SKILL_SLUGS: Final[frozenset[str]] = frozenset(BUILT_IN_SKILLS) | frozenset(
    EXTERNAL_APP_BUILT_IN_SKILL_IDS.values()
)


def ensure_custom_skill(skill: Skill) -> None:
    """Block any mutation on a built-in skill row."""
    if skill.built_in_skill_id is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.slug}' is a built-in and cannot be modified.",
        )


def reject_reserved_skill_slug(filename: str | None) -> None:
    """Reject a bundle whose slug collides with codified skill identifiers."""
    slug = slug_from_filename(filename)
    if slug in _RESERVED_SKILL_SLUGS:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"slug '{slug}' is reserved")


def ensure_owned_personal_skill(
    skill: Skill,
    user: User,
    db_session: Session,
) -> None:
    """Gate user-endpoint mutations to the caller's own personal skills."""
    ensure_custom_skill(skill)
    if skill.author_user_id != user.id:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
    if skill.public_permission is not None or skill_ids_with_grants(
        [skill.id], db_session
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "This skill is managed by your organization and can no longer "
            "be modified through personal skill endpoints.",
        )


@contextmanager
def ingested_skill_bundle(
    *,
    bundle_file: BinaryIO,
    filename: str | None,
    slug: str | None = None,
) -> Iterator[IngestedBundle]:
    file_store = get_default_file_store()
    with ingest_bundle_with_cleanup(
        read_bundle_file(bundle_file), filename, file_store, slug=slug
    ) as ingested:
        yield ingested


def replace_custom_skill_bundle_contents(
    *,
    skill: Skill,
    bundle_file: BinaryIO,
    filename: str | None,
    db_session: Session,
) -> Skill:
    with ingested_skill_bundle(
        bundle_file=bundle_file,
        filename=filename,
        slug=skill.slug,
    ) as ingested:
        updated, old_file_id = replace_skill_bundle(
            skill_id=skill.id,
            new_bundle_file_id=ingested.bundle_file_id,
            new_bundle_sha256=ingested.bundle_sha256,
            new_name=ingested.name,
            new_description=ingested.description,
            db_session=db_session,
        )
        db_session.commit()

    push_skill_to_affected_sandboxes(updated, db_session)
    delete_bundle_blob(get_default_file_store(), old_file_id)
    return updated
