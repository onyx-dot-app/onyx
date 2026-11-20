import io
import zipfile
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.db.enums import SkillSharePermission
from onyx.db.models import Plugin, User
from onyx.db.plugin import SYNCED_PLUGIN_LOCKED
from onyx.db.skill import lock_skill_for_save
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill import api
from onyx.server.features.skill.models import (
    SkillBulkActionRequest,
    SkillBulkShareRequest,
    SkillBulkSharing,
    SkillPatchRequest,
    SkillPublishRequest,
    SkillShareRequest,
    SkillUserShareRequest,
    SkillVersionRestoreRequest,
    TransferSkillOwnershipRequest,
)
from onyx.skills.marketplace import sync
from tests.external_dependency_unit.craft.fake_github import FakeGitHub
from tests.external_dependency_unit.craft.marketplace.helpers import (
    OWNER,
    REPO,
    Connections,
    make_marketplace,
    plugin_files,
    synced_plugins,
)
from tests.unit.onyx.skills.marketplace_fixtures import skill_md


def _zip_upload(name: str) -> UploadFile:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle_zip:
        bundle_zip.writestr("SKILL.md", skill_md(name))
    return UploadFile(file=io.BytesIO(output.getvalue()), filename=f"{name}.zip")


@pytest.fixture
def synced(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> Plugin:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    sync.sync_marketplace(marketplace.id)
    return synced_plugins(db_session, marketplace.id)["alpha"]


def _refused(call: Callable[[], object]) -> None:
    with pytest.raises(OnyxError) as exc:
        call()
    assert exc.value.detail == SYNCED_PLUGIN_LOCKED


def test_content_and_ownership_changes_are_refused(
    db_session: Session, users: tuple[User, User, User], synced: Plugin
) -> None:
    owner = db_session.get(User, users[0].id)
    assert owner is not None
    plugin_id: UUID = synced.id
    version_id = synced.current_version_id
    calls: list[Callable[[], object]] = [
        lambda: api.replace_current_user_skill_bundle(
            plugin_id, _zip_upload("alpha"), None, owner, db_session
        ),
        lambda: api.upload_current_user_skill_files(
            plugin_id, _zip_upload("alpha"), None, owner, db_session
        ),
        lambda: api.remove_current_user_skill_file(
            plugin_id, "skills/alpha/SKILL.md", None, owner, db_session
        ),
        lambda: api.patch_current_user_skill(
            plugin_id, SkillPatchRequest(description="New"), owner, db_session
        ),
        lambda: api.restore_custom_skill_version(
            plugin_id,
            version_id,
            SkillVersionRestoreRequest(base_version_id=version_id),
            owner,
            db_session,
        ),
        lambda: api.publish_current_user_skill(
            plugin_id, SkillPublishRequest(), owner, db_session
        ),
        lambda: api.transfer_current_user_skill_ownership(
            plugin_id,
            TransferSkillOwnershipRequest(new_owner_user_id=users[1].id),
            owner,
            db_session,
        ),
        lambda: api.delete_current_user_skill(plugin_id, owner, db_session),
        lambda: api.share_current_user_skill(
            plugin_id,
            SkillShareRequest(public_permission=SkillSharePermission.VIEWER),
            owner,
            db_session,
        ),
    ]
    # The skill editor routes take skills only, so a plugin is not found
    # there; the shared save lock refuses a synced plugin too.
    for call in calls[:4]:
        with pytest.raises(OnyxError, match="Skill not found"):
            call()
        db_session.rollback()
    _refused(lambda: lock_skill_for_save(synced, owner, db_session))
    db_session.rollback()
    for call in calls[4:]:
        _refused(call)
        db_session.rollback()

    result = api.bulk_update_skills(
        SkillBulkActionRequest(skill_ids=[plugin_id], action="delete"),
        owner,
        db_session,
    )
    assert result.succeeded == []
    assert [failure.detail for failure in result.failed] == [SYNCED_PLUGIN_LOCKED]
    db_session.expire_all()
    assert db_session.get(Plugin, plugin_id) is not None


def test_sharing_still_works(
    db_session: Session, users: tuple[User, User, User], synced: Plugin
) -> None:
    owner = db_session.get(User, users[0].id)
    assert owner is not None
    response = api.share_current_user_skill(
        synced.id,
        SkillShareRequest(
            user_shares=[
                SkillUserShareRequest(
                    user_id=users[1].id, permission=SkillSharePermission.VIEWER
                )
            ]
        ),
        owner,
        db_session,
    )
    assert [share.user.id for share in response.user_shares] == [users[1].id]
    assert response.content_locked
    assert response.marketplace is not None
    assert response.marketplace.repository == f"{OWNER}/{REPO}"

    bulk = api.bulk_update_skills(
        SkillBulkShareRequest(
            skill_ids=[synced.id],
            action="share",
            sharing=SkillBulkSharing(
                user_shares=[
                    SkillUserShareRequest(
                        user_id=users[2].id, permission=SkillSharePermission.VIEWER
                    )
                ]
            ),
        ),
        owner,
        db_session,
    )
    assert bulk.succeeded == [synced.id]
