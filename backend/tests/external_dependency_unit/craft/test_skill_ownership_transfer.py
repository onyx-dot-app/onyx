from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import onyx.server.features.skill.service as skill_service
from onyx.db.enums import AccountType
from onyx.db.enums import SkillSharePermission
from onyx.db.models import Skill
from onyx.db.models import Skill__User
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.models import TransferSkillOwnershipRequest
from tests.external_dependency_unit.craft.db_helpers import make_sandbox
from tests.external_dependency_unit.craft.db_helpers import make_skill
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.craft.db_helpers import share_skill_with_user


def _owned_skill(db_session: Session, owner: User) -> Skill:
    skill = make_skill(db_session)
    skill.author_user_id = owner.id
    db_session.flush()
    return skill


def _share_row(
    db_session: Session,
    skill: Skill,
    user: User,
) -> Skill__User | None:
    return db_session.scalar(
        select(Skill__User).where(
            Skill__User.skill_id == skill.id,
            Skill__User.user_id == user.id,
        )
    )


@pytest.fixture(autouse=True)
def push_calls(monkeypatch: pytest.MonkeyPatch) -> list[set[object]]:
    calls: list[set[object]] = []
    monkeypatch.setattr(
        skill_service,
        "push_skills_for_users",
        lambda user_ids, _db_session: calls.append(set(user_ids)),
    )
    return calls


def test_owner_transfers_to_active_user(
    db_session: Session,
    push_calls: list[set[object]],
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    new_owner = make_user(db_session, role=UserRole.BASIC)
    skill = _owned_skill(db_session, owner)
    share_skill_with_user(
        db_session,
        skill,
        new_owner,
        SkillSharePermission.VIEWER,
    )

    transferred = skill_service.transfer_custom_skill_ownership_for_user(
        skill_id=skill.id,
        transfer=TransferSkillOwnershipRequest(new_owner_user_id=new_owner.id),
        user=owner,
        db_session=db_session,
    )

    assert transferred.author_user_id == new_owner.id
    assert _share_row(db_session, transferred, new_owner) is None
    previous_owner_share = _share_row(db_session, transferred, owner)
    assert previous_owner_share is not None
    assert previous_owner_share.permission == SkillSharePermission.EDITOR
    assert push_calls == [set()]


def test_transfer_pushes_previous_and_new_owner_sandboxes(
    db_session: Session,
    push_calls: list[set[object]],
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    new_owner = make_user(db_session, role=UserRole.BASIC)
    make_sandbox(db_session, owner)
    make_sandbox(db_session, new_owner)
    skill = _owned_skill(db_session, owner)

    skill_service.transfer_custom_skill_ownership_for_user(
        skill_id=skill.id,
        transfer=TransferSkillOwnershipRequest(new_owner_user_id=new_owner.id),
        user=owner,
        db_session=db_session,
    )

    assert push_calls == [{owner.id, new_owner.id}]


@pytest.mark.parametrize(
    "permission",
    [SkillSharePermission.VIEWER, SkillSharePermission.EDITOR],
)
def test_non_owner_sharee_cannot_transfer(
    db_session: Session,
    permission: SkillSharePermission,
    push_calls: list[set[object]],
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    sharee = make_user(db_session, role=UserRole.BASIC)
    target = make_user(db_session, role=UserRole.BASIC)
    skill = _owned_skill(db_session, owner)
    share_skill_with_user(db_session, skill, sharee, permission)

    with pytest.raises(OnyxError) as exc_info:
        skill_service.transfer_custom_skill_ownership_for_user(
            skill_id=skill.id,
            transfer=TransferSkillOwnershipRequest(new_owner_user_id=target.id),
            user=sharee,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.refresh(skill)
    assert skill.author_user_id == owner.id
    assert _share_row(db_session, skill, sharee) is not None
    assert push_calls == []


def test_transfer_rejects_inactive_target(
    db_session: Session,
    push_calls: list[set[object]],
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    target = make_user(db_session, role=UserRole.BASIC)
    target.is_active = False
    skill = _owned_skill(db_session, owner)
    db_session.flush()

    with pytest.raises(OnyxError) as exc_info:
        skill_service.transfer_custom_skill_ownership_for_user(
            skill_id=skill.id,
            transfer=TransferSkillOwnershipRequest(new_owner_user_id=target.id),
            user=owner,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    db_session.refresh(skill)
    assert skill.author_user_id == owner.id
    assert _share_row(db_session, skill, target) is None
    assert push_calls == []


def test_transfer_rejects_unsupported_target_account_type(
    db_session: Session,
    push_calls: list[set[object]],
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    target = make_user(
        db_session,
        role=UserRole.BASIC,
    )
    target.account_type = AccountType.BOT
    skill = _owned_skill(db_session, owner)
    db_session.flush()

    with pytest.raises(OnyxError) as exc_info:
        skill_service.transfer_custom_skill_ownership_for_user(
            skill_id=skill.id,
            transfer=TransferSkillOwnershipRequest(new_owner_user_id=target.id),
            user=owner,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    db_session.refresh(skill)
    assert skill.author_user_id == owner.id
    assert _share_row(db_session, skill, target) is None
    assert push_calls == []


def test_admin_transfers_vacant_skill(
    db_session: Session,
    push_calls: list[set[object]],
) -> None:
    admin = make_user(db_session, role=UserRole.ADMIN)
    target = make_user(db_session, role=UserRole.BASIC)
    skill = make_skill(db_session)

    transferred = skill_service.transfer_custom_skill_ownership_for_user(
        skill_id=skill.id,
        transfer=TransferSkillOwnershipRequest(new_owner_user_id=target.id),
        user=admin,
        db_session=db_session,
    )

    assert transferred.author_user_id == target.id
    assert _share_row(db_session, transferred, admin) is None
    assert push_calls == [set()]


def test_admin_cannot_transfer_owned_skill(
    db_session: Session,
    push_calls: list[set[object]],
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    admin = make_user(db_session, role=UserRole.ADMIN)
    target = make_user(db_session, role=UserRole.BASIC)
    skill = _owned_skill(db_session, owner)

    with pytest.raises(OnyxError) as exc_info:
        skill_service.transfer_custom_skill_ownership_for_user(
            skill_id=skill.id,
            transfer=TransferSkillOwnershipRequest(new_owner_user_id=target.id),
            user=admin,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.refresh(skill)
    assert skill.author_user_id == owner.id
    assert _share_row(db_session, skill, target) is None
    assert push_calls == []


def test_transfer_rejects_missing_target(
    db_session: Session,
    push_calls: list[set[object]],
) -> None:
    owner = make_user(db_session, role=UserRole.BASIC)
    skill = _owned_skill(db_session, owner)

    with pytest.raises(OnyxError) as exc_info:
        skill_service.transfer_custom_skill_ownership_for_user(
            skill_id=skill.id,
            transfer=TransferSkillOwnershipRequest(new_owner_user_id=uuid4()),
            user=owner,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND
    db_session.refresh(skill)
    assert skill.author_user_id == owner.id
    assert push_calls == []
