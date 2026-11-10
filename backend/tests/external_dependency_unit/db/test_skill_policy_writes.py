import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.db.enums import Permission
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.models import (
    Marketplace,
    Skill,
    User__UserGroup,
    UserGroup,
    UserSkillPreference,
)
from onyx.db.resource_access import ResourceAccessChange, mutate_resource_access
from onyx.db.skill import (
    SkillAccessAdapter,
    enable_new_skill_if_name_available__no_commit,
    set_skill_enabled_for_user,
    skill_user_states,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.response_helpers import (
    skill_response_for_user,
    skills_list_response_for_user,
)
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_group,
    make_skill,
    make_user,
    share_skill_with_group,
)
from tests.external_dependency_unit.db.test_marketplace_api import client_for
from tests.external_dependency_unit.db.test_skill_access_mutations import manager
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")


@pytest.mark.parametrize(
    "company,group",
    [
        (Policy.REQUIRED, Policy.NOT_AVAILABLE),
        (Policy.AVAILABLE, Policy.REQUIRED),
        (Policy.NOT_AVAILABLE, Policy.AVAILABLE),
    ],
)
def test_auto_enable_uses_effective_policy(
    session: Session, company: Policy, group: Policy
) -> None:
    user = make_user(session, standard_account=True)
    skill = make_skill(session, author_user_id=user.id)
    skill.installation_policy = company
    team = make_group(session)
    add_user_to_group(session, user, team)
    share_skill_with_group(session, skill, team).installation_policy = group
    if group == Policy.REQUIRED:
        session.add(
            UserSkillPreference(
                user_id=user.id, skill_id=skill.id, name=skill.name, enabled=False
            )
        )
    session.flush()
    assert enable_new_skill_if_name_available__no_commit(skill, user.id, session) is (
        group != Policy.NOT_AVAILABLE
    )
    pref = session.get(UserSkillPreference, (user.id, skill.id))
    if group == Policy.REQUIRED:
        assert pref is not None and not pref.enabled
    elif group == Policy.NOT_AVAILABLE:
        assert pref is None
    else:
        assert pref is not None and pref.enabled


def test_membership_updates_response_and_toggles(session: Session) -> None:
    user = make_user(session, standard_account=True)
    skill = make_skill(session, author_user_id=user.id)
    skill.installation_policy = Policy.REQUIRED
    team = make_group(session)
    share_skill_with_group(
        session, skill, team
    ).installation_policy = Policy.NOT_AVAILABLE
    add_user_to_group(session, user, team)
    session.flush()
    for expected in (Policy.NOT_AVAILABLE, Policy.REQUIRED):
        response = skill_response_for_user(skill, user, session)
        listed = skills_list_response_for_user([skill], user, session).customs[0]
        assert (
            response.installation_policy
            == listed.installation_policy
            == Policy.REQUIRED
        )
        assert (
            response.effective_installation_policy
            == listed.effective_installation_policy
            == expected
        )
        assert response.can_toggle is False
        with (
            pytest.raises(OnyxError, match="cannot be enabled"),
            session.begin_nested(),
        ):
            set_skill_enabled_for_user(
                skill_id=skill.id, enabled=True, user=user, db_session=session
            )
        session.execute(
            delete(User__UserGroup).where(
                User__UserGroup.user_id == user.id,
                User__UserGroup.user_group_id == team.id,
            )
        )
    assert skill_user_states(user, [skill.id], session)[skill.id].enabled


@pytest.mark.parametrize("policy", [Policy.REQUIRED, Policy.NOT_AVAILABLE])
@pytest.mark.parametrize("add_only", [False, True])
def test_owner_cannot_remove_managed_policy_by_omitting_group(
    session: Session, policy: Policy, add_only: bool
) -> None:
    owner = make_user(session, standard_account=True)
    source = Marketplace(
        name="Personal source",
        owner_user_id=owner.id,
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(owner="acme", repo="tools", ref="main"),
    )
    session.add(source)
    session.flush()
    skill = make_skill(session, author_user_id=owner.id)
    skill.marketplace_id = source.id
    skill.marketplace_entry_key = "entry/skill"
    group = make_group(session)
    share_skill_with_group(session, skill, group).installation_policy = policy
    session.flush()

    def remove() -> None:
        mutate_resource_access(
            [skill.id],
            ResourceAccessChange(group_shares={}),
            owner,
            session,
            SkillAccessAdapter(),
            add_only=add_only,
            allow_management=False,
        )

    if add_only:
        remove()
    else:
        with pytest.raises(OnyxError), session.begin_nested():
            remove()
    session.refresh(skill, ["group_shares"])
    assert len(skill.group_shares) == 1
    assert skill.group_shares[0].installation_policy == policy
    # An owner retains audience control when no management policy is removed.
    skill.group_shares[0].installation_policy = None
    session.flush()
    mutate_resource_access(
        [skill.id],
        ResourceAccessChange(group_shares={}),
        owner,
        session,
        SkillAccessAdapter(),
        allow_management=False,
    )
    assert skill.group_shares == []


def test_explicit_enable_clears_hidden_saved_choice(session: Session) -> None:
    user = make_user(session, standard_account=True)
    hidden = make_skill(session, is_public=True)
    selected = make_skill(session, author_user_id=user.id, name=hidden.name)
    group = make_group(session)
    add_user_to_group(session, user, group)
    share_skill_with_group(
        session, hidden, group
    ).installation_policy = Policy.NOT_AVAILABLE
    saved = UserSkillPreference(
        user_id=user.id, skill_id=hidden.id, name=hidden.name, enabled=True
    )
    session.add(saved)
    session.flush()
    set_skill_enabled_for_user(
        skill_id=selected.id, enabled=True, user=user, db_session=session
    )
    session.flush()
    session.refresh(saved)
    assert not saved.enabled
    choice = session.get(UserSkillPreference, (user.id, selected.id))
    assert choice is not None and choice.enabled


@pytest.mark.parametrize("role", ["global", "scoped", "owner", "limited"])
@pytest.mark.parametrize("group_policy", [True, False])
def test_not_available_requires_policy_authority(
    session: Session, role: str, group_policy: bool
) -> None:
    if role == "owner":
        actor = make_user(session, standard_account=True)
        team = make_group(session)
    else:
        actor, group_id = manager(session, global_access=role != "scoped")
        team = session.get(UserGroup, group_id)
        assert team is not None
    skill = make_skill(session, author_user_id=actor.id)
    share_skill_with_group(session, skill, team)
    session.flush()
    sharing = (
        {
            "group_shares": [
                {
                    "group_id": team.id,
                    "permission": "VIEWER",
                    "installation_policy": "NOT_AVAILABLE",
                }
            ]
        }
        if group_policy
        else {"installation_policy": "NOT_AVAILABLE"}
    )
    with client_for(
        actor, session, [Permission.BASIC_ACCESS] if role == "limited" else None
    ) as client:
        response = client.patch(f"/skills/custom/{skill.id}/share", json=sharing)
    allowed = role == "global" or (role == "scoped" and group_policy)
    assert response.status_code == (200 if allowed else 403), response.text


def test_group_required_delete_requires_management(session: Session) -> None:
    owner = make_user(session, standard_account=True)
    skill = make_skill(session, author_user_id=owner.id)
    share_skill_with_group(
        session, skill, make_group(session)
    ).installation_policy = Policy.REQUIRED
    session.flush()
    with client_for(owner, session) as client:
        response = client.delete(f"/skills/custom/{skill.id}")
    assert response.status_code == 403, response.text


def test_builtin_response_has_both_policy_fields(session: Session) -> None:
    user = make_user(session, standard_account=True)
    builtin = session.scalar(select(Skill).where(Skill.built_in_skill_id == "pptx"))
    assert builtin is not None
    response = skill_response_for_user(builtin, user, session)
    listed = skills_list_response_for_user([builtin], user, session).builtins[0]
    assert (
        response.installation_policy == listed.installation_policy == Policy.AVAILABLE
    )
    assert (
        response.effective_installation_policy
        == listed.effective_installation_policy
        == Policy.AVAILABLE
    )
