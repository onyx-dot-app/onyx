"""The read-side permission projection must equal write-side enforcement.

Each test drives the REAL guard and asserts the extracted boolean the projection
stamps matches whether the guard raises, across an actor matrix — so the affordance
the client renders can't silently drift from what the backend enforces.
"""

import asyncio
import inspect
from collections.abc import Callable
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ee.onyx.db.analytics import user_can_view_assistant_stats
from ee.onyx.db.token_limit import insert_user_group_token_rate_limit
from ee.onyx.server.token_rate_limits.api import _authorize_group_token_rate_limit_write
from ee.onyx.server.token_rate_limits.api import get_group_token_limit_settings
from ee.onyx.server.user_group.api import delete_user_group
from ee.onyx.server.user_group.api import set_user_group_permissions
from onyx.auth.permission_projection import CC_PAIR_ACTIONS
from onyx.auth.permission_projection import cc_pair_permissions
from onyx.auth.permission_projection import CUSTOM_SKILL_ACTIONS
from onyx.auth.permission_projection import custom_skill_permissions
from onyx.auth.permission_projection import DOCUMENT_SET_ACTIONS
from onyx.auth.permission_projection import document_set_permissions
from onyx.auth.permission_projection import MCP_SERVER_ACTIONS
from onyx.auth.permission_projection import mcp_server_permissions
from onyx.auth.permission_projection import PERSONA_ACTIONS
from onyx.auth.permission_projection import persona_permissions
from onyx.auth.permission_projection import TOOL_ACTIONS
from onyx.auth.permission_projection import tool_permissions
from onyx.auth.permission_projection import USER_GROUP_ACTIONS
from onyx.auth.permission_projection import user_group_permissions
from onyx.auth.permissions import has_global_permission
from onyx.auth.permissions import has_permission
from onyx.auth.scoped_permissions import assert_manages_group
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.auth.scoped_permissions import manages_group
from onyx.auth.scoped_permissions import within_scope
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.connector_credential_pair import (
    get_connector_credential_pair_from_id_for_user,
)
from onyx.db.document_set import fetch_all_document_sets_for_user
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import MCPServerStatus
from onyx.db.enums import Permission
from onyx.db.enums import PermissionAuthority
from onyx.db.enums import PersonaSharePermission
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import DocumentSet
from onyx.db.models import DocumentSet__UserGroup
from onyx.db.models import MCPServer
from onyx.db.models import Persona
from onyx.db.models import Persona__Tool
from onyx.db.models import Persona__User
from onyx.db.models import Persona__UserGroup
from onyx.db.models import Skill
from onyx.db.models import Skill__UserGroup
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserGroup__ConnectorCredentialPair
from onyx.db.persona import _assert_persona_update_within_managed_scope
from onyx.db.persona import can_delete_persona
from onyx.db.persona import can_edit_persona
from onyx.db.persona import can_view_persona_stats
from onyx.db.persona import fetch_persona_by_id_for_user
from onyx.db.persona import get_persona_by_id
from onyx.db.persona import is_persona_editable_by_user
from onyx.db.persona import persona_edit_within_scope
from onyx.db.skill import get_group_ids_for_skill
from onyx.db.token_limit import insert_global_token_rate_limit
from onyx.db.tools import can_manage_mcp_server
from onyx.db.tools import can_manage_own_tool
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp.api import _ensure_mcp_server_owner_or_admin
from onyx.server.features.mcp.api import _ensure_mcp_server_viewable
from onyx.server.features.persona.api import delete_persona
from onyx.server.features.persona.models import PersonaUpsertRequest
from onyx.server.features.tool.api import _get_manageable_custom_tool
from onyx.server.manage.administrative import create_deletion_attempt_for_connector_id
from onyx.server.token_rate_limits.models import TokenRateLimitArgs
from tests.external_dependency_unit.conftest import create_test_user


def _guard_raises(
    guard: Callable[..., object], *args: object, **kwargs: object
) -> bool:
    try:
        guard(*args, **kwargs)
        return False
    except OnyxError:
        return True


def _route_admits(
    route_func: Callable[..., object], guard_param: str, actor: User
) -> bool:
    """True iff the route's ``require_permission`` admits ``actor`` (unrestricted token).
    Runs the real dependency, so the assertion tracks the route decorator — not the bool
    that built the map, which can't catch a FULL_ADMIN vs MANAGE_USER_GROUPS drift."""
    depends = inspect.signature(route_func).parameters[guard_param].default
    request = SimpleNamespace(state=SimpleNamespace(token_scopes=None))
    return not _guard_raises(lambda: asyncio.run(depends.dependency(request, actor)))


def _make_group(db_session: Session) -> UserGroup:
    group = UserGroup(name=f"proj-contract-{uuid4().hex[:12]}")
    db_session.add(group)
    db_session.flush()
    return group


def _manage(db_session: Session, user: User, *groups: UserGroup) -> None:
    for group in groups:
        db_session.add(
            User__UserGroup(user_id=user.id, user_group_id=group.id, is_manager=True)
        )
    user.is_group_manager = True
    db_session.commit()


def _make_cc_pair(
    db_session: Session, *, is_public: bool, groups: list[UserGroup]
) -> ConnectorCredentialPair:
    connector = Connector(
        name=f"proj-conn-{uuid4().hex[:12]}",
        source=DocumentSource.FILE,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(source=DocumentSource.FILE, credential_json={})
    db_session.add(credential)
    db_session.flush()

    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"proj-ccpair-{uuid4().hex[:12]}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC if is_public else AccessType.PRIVATE,
    )
    db_session.add(cc_pair)
    db_session.flush()
    for group in groups:
        db_session.add(
            UserGroup__ConnectorCredentialPair(
                user_group_id=group.id, cc_pair_id=cc_pair.id, is_current=True
            )
        )
    db_session.commit()
    return cc_pair


def test_cc_pair_projection_matches_gates(db_session: Session) -> None:
    """Each key is pinned to the real route, not the bool that built it: edit → the editable
    query (which must agree with the within_scope write decision); delete → the deletion route's
    GATE 1 (global MANAGE_CONNECTORS, no allow_scope); publish → the associate route's real GATE 2
    (assert_within_scope for the PUBLIC state). So this fails if either route starts admitting a
    scoped manager — a scoped manager edits a managed connector but can never delete/publish it."""
    managed = _make_group(db_session)

    in_scope = create_test_user(db_session, "proj-cc-inscope")
    _manage(db_session, in_scope, managed)
    in_scope.effective_permissions = []

    out_scope = create_test_user(db_session, "proj-cc-outscope")
    _manage(db_session, out_scope, _make_group(db_session))
    out_scope.effective_permissions = []

    admin = create_test_user(db_session, "proj-cc-admin", is_admin=True)
    db_session.commit()

    cc_pair = _make_cc_pair(db_session, is_public=False, groups=[managed])

    for actor in (in_scope, out_scope, admin):
        # edit: the real editable query must agree with the within_scope write decision
        is_editable = (
            get_connector_credential_pair_from_id_for_user(
                cc_pair.id, db_session, actor, get_editable=True
            )
            is not None
        )
        scope_decision = within_scope(
            actor,
            db_session,
            permission=Permission.MANAGE_CONNECTORS,
            current_group_ids=[managed.id],
            requested_group_ids=[managed.id],
            is_non_public=True,
        )
        assert is_editable == scope_decision, actor.email

        # delete: the deletion route's GATE 1 (global only, no allow_scope)
        delete_admits = _route_admits(
            create_deletion_attempt_for_connector_id, "user", actor
        )
        # publish: the associate route's real GATE 2 for the PUBLIC state (is_non_public=False)
        publish_enforced = not _guard_raises(
            assert_within_scope,
            actor,
            db_session,
            permission=Permission.MANAGE_CONNECTORS,
            current_group_ids=[managed.id],
            requested_group_ids=[managed.id],
            is_non_public=False,
        )

        tags = cc_pair_permissions(
            is_editable=is_editable,
            is_connectors_admin=has_global_permission(
                actor, Permission.MANAGE_CONNECTORS
            ),
        )
        assert tags["edit"] == scope_decision, actor.email
        assert tags["delete"] == delete_admits, actor.email
        assert tags["publish"] == publish_enforced, actor.email

    # concrete: an in-scope manager edits but can neither delete nor publish
    in_scope_editable = (
        get_connector_credential_pair_from_id_for_user(
            cc_pair.id, db_session, in_scope, get_editable=True
        )
        is not None
    )
    assert cc_pair_permissions(
        is_editable=in_scope_editable,
        is_connectors_admin=has_global_permission(
            in_scope, Permission.MANAGE_CONNECTORS
        ),
    ) == {"edit": True, "delete": False, "publish": False}


def test_cc_pair_projection_key_coverage() -> None:
    stamped = set(cc_pair_permissions(is_editable=True, is_connectors_admin=True))
    assert stamped == set(CC_PAIR_ACTIONS), (
        "cc_pair projection keys drifted from the declared CC_PAIR_ACTIONS vocabulary"
    )


def _make_persona(
    db_session: Session, *, owner: User, is_public: bool, groups: list[UserGroup]
) -> Persona:
    persona = Persona(
        name=f"proj-persona-{uuid4().hex[:12]}",
        description="contract",
        public_permission=PersonaSharePermission.EDITOR,
        user_id=owner.id,
        is_public=is_public,
    )
    db_session.add(persona)
    db_session.flush()
    for group in groups:
        db_session.add(
            Persona__UserGroup(persona_id=persona.id, user_group_id=group.id)
        )
    db_session.commit()
    return persona


def _make_doc_set(
    db_session: Session, *, is_public: bool, groups: list[UserGroup]
) -> DocumentSet:
    doc_set = DocumentSet(name=f"proj-ds-{uuid4().hex[:12]}", is_public=is_public)
    db_session.add(doc_set)
    db_session.flush()
    for group in groups:
        db_session.add(
            DocumentSet__UserGroup(document_set_id=doc_set.id, user_group_id=group.id)
        )
    db_session.commit()
    return doc_set


def test_persona_projection_matches_gates(db_session: Session) -> None:
    """edit tracks the read-editable AND managed-scope decision the write guard enforces;
    view_stats tracks the real owner-or-admin stats gate; the rest are global-only."""
    managed = _make_group(db_session)
    unmanaged = _make_group(db_session)

    in_scope = create_test_user(db_session, "b-persona-in")
    _manage(db_session, in_scope, managed)
    in_scope.effective_permissions = []

    out_scope = create_test_user(db_session, "b-persona-out")
    _manage(db_session, out_scope, unmanaged)
    out_scope.effective_permissions = []

    owner = create_test_user(db_session, "b-persona-owner")
    owner.effective_permissions = []

    admin = create_test_user(db_session, "b-persona-admin", is_admin=True)
    db_session.commit()

    persona = _make_persona(db_session, owner=owner, is_public=False, groups=[managed])
    group_ids = [group.id for group in persona.groups]

    def edit_guard_raises(actor: User) -> bool:
        request = PersonaUpsertRequest(
            name=persona.name,
            description=persona.description or "",
            system_prompt="",
            task_prompt="",
            datetime_aware=False,
            document_set_ids=[],
            tool_ids=[],
            groups=group_ids,
            is_public=persona.is_public,
        )
        return _guard_raises(
            _assert_persona_update_within_managed_scope,
            persona.id,
            request,
            actor,
            db_session,
        )

    for actor in (in_scope, out_scope, owner, admin):
        # read bool == the real write guard's managed-scope decision
        assert persona_edit_within_scope(
            actor, db_session, group_ids=group_ids, is_public=persona.is_public
        ) == (not edit_guard_raises(actor)), actor.email
        # view_stats == the real owner-or-admin stats gate
        assert can_view_persona_stats(actor, persona) == user_can_view_assistant_stats(
            db_session, actor, persona.id
        ), actor.email
        # delete == the real delete handler's ownership gate (get_persona_by_id is_for_edit)
        try:
            get_persona_by_id(persona_id=persona.id, user=actor, db_session=db_session)
            delete_allowed = True
        except ValueError:
            delete_allowed = False
        assert can_delete_persona(actor, persona, db_session) == delete_allowed, (
            actor.email
        )

    # concrete: an in-scope manager can edit/share but not view_stats/delete/feature/reorder
    in_scope_editable = is_persona_editable_by_user(db_session, persona.id, in_scope)
    mgr_map = persona_permissions(
        can_edit=can_edit_persona(
            in_scope, persona, db_session, is_editable=in_scope_editable
        ),
        can_share=in_scope_editable,
        can_view_stats=can_view_persona_stats(in_scope, persona),
        can_delete=can_delete_persona(in_scope, persona, db_session),
        holds_add_agents=has_permission(in_scope, Permission.ADD_AGENTS)
        is not PermissionAuthority.NONE,
        is_manage_agents_admin=has_global_permission(
            in_scope, Permission.MANAGE_AGENTS
        ),
        is_full_admin=has_global_permission(
            in_scope, Permission.FULL_ADMIN_PANEL_ACCESS
        ),
    )
    assert mgr_map["edit"] is True and mgr_map["share"] is True
    assert mgr_map["view_stats"] is False
    assert not any(mgr_map[a] for a in ("delete", "publish", "feature", "reorder"))


def test_delete_persona_route_admits_scoped_owner(
    enable_ee: None,  # noqa: ARG001 -- side-effect fixture: forces EE for the whole test
    db_session: Session,
) -> None:
    """The delete route must admit a scoped ADD_AGENTS holder (allow_scope=True); otherwise an
    owner who holds ADD_AGENTS only by scope is 403'd before the GATE-2 ownership check, making
    the projection's delete=true a lie for them. The gate checks above can't catch a missing
    allow_scope. enable_ee so ADD_AGENTS is genuinely scoped — CE auto-grants it globally, which
    would pass the gate regardless and prove nothing."""
    manager = create_test_user(db_session, "del-route-mgr")
    _manage(db_session, manager, _make_group(db_session))
    manager.effective_permissions = []
    db_session.commit()

    # Premise: if the manager ever holds ADD_AGENTS globally, the route check below tests
    # nothing — fail loudly here instead of passing vacuously.
    assert (
        has_permission(manager, Permission.ADD_AGENTS) is PermissionAuthority.SCOPED
    ), "manager should hold ADD_AGENTS only by scope"
    assert _route_admits(delete_persona, "user", manager), (
        "delete route must admit scoped managers at GATE 1 (allow_scope=True)"
    )


def test_persona_share_projection_tracks_share_guard_not_edit(
    db_session: Session,
) -> None:
    """share follows the share guard (fetch_persona_by_id_for_user / get_editable), which is
    broader than edit's managed-scope AND gate: an EDITOR-shared manager outside the agent's
    groups may share it but not update it, so ``share`` must not reuse ``can_edit``."""
    managed = _make_group(db_session)
    unmanaged = _make_group(db_session)

    # Manager of `unmanaged`, EDITOR-shared on an agent grouped in `managed` (out of scope).
    editor = create_test_user(db_session, "share-editor")
    _manage(db_session, editor, unmanaged)
    editor.effective_permissions = []

    owner = create_test_user(db_session, "share-owner")
    owner.effective_permissions = []
    db_session.commit()

    persona = _make_persona(db_session, owner=owner, is_public=False, groups=[managed])
    db_session.add(
        Persona__User(
            persona_id=persona.id,
            user_id=editor.id,
            permission=PersonaSharePermission.EDITOR,
        )
    )
    db_session.commit()

    is_editable = is_persona_editable_by_user(db_session, persona.id, editor)
    can_edit = can_edit_persona(editor, persona, db_session, is_editable=is_editable)

    # The real share-endpoint gate: does the editable fetch admit them?
    try:
        fetch_persona_by_id_for_user(
            db_session=db_session, persona_id=persona.id, user=editor, get_editable=True
        )
        share_allowed = True
    except HTTPException:
        share_allowed = False

    assert is_editable is True  # EDITOR-shared → in the editable set
    assert can_edit is False  # ...but out of managed scope → can't update
    assert share_allowed is True  # ...yet the share endpoint admits them

    tags = persona_permissions(
        can_edit=can_edit,
        can_share=is_editable,
        can_view_stats=can_view_persona_stats(editor, persona),
        can_delete=can_delete_persona(editor, persona, db_session),
        holds_add_agents=has_permission(editor, Permission.ADD_AGENTS)
        is not PermissionAuthority.NONE,
        is_manage_agents_admin=has_global_permission(editor, Permission.MANAGE_AGENTS),
        is_full_admin=has_global_permission(editor, Permission.FULL_ADMIN_PANEL_ACCESS),
    )
    assert tags["share"] == share_allowed  # share tracks the share guard...
    assert tags["edit"] is False  # ...not the stricter edit guard


def test_persona_edit_share_editable_without_add_agents(
    enable_ee: None,  # noqa: ARG001 -- side-effect fixture: forces EE for the whole test
    db_session: Session,
) -> None:
    """edit and share gate on editable alone (their routes are BASIC_ACCESS): an EDITOR-shared
    user without ADD_AGENTS may still edit and manage sharing, so both are True. enable_ee
    because CE auto-grants ADD_AGENTS, which would mask that they need no create permission."""
    owner = create_test_user(db_session, "add-share-owner")
    owner.effective_permissions = []
    # EDITOR-shared, but no ADD_AGENTS authority: not a manager, empty permissions.
    editor = create_test_user(db_session, "add-share-editor")
    editor.effective_permissions = []
    db_session.commit()

    persona = _make_persona(db_session, owner=owner, is_public=False, groups=[])
    db_session.add(
        Persona__User(
            persona_id=persona.id,
            user_id=editor.id,
            permission=PersonaSharePermission.EDITOR,
        )
    )
    db_session.commit()

    is_editable = is_persona_editable_by_user(db_session, persona.id, editor)
    holds_add_agents = (
        has_permission(editor, Permission.ADD_AGENTS) is not PermissionAuthority.NONE
    )
    assert is_editable is True  # EDITOR-shared → editable
    assert holds_add_agents is False  # ...but no ADD_AGENTS authority under EE

    tags = persona_permissions(
        can_edit=can_edit_persona(editor, persona, db_session, is_editable=is_editable),
        can_share=is_editable,
        can_view_stats=can_view_persona_stats(editor, persona),
        can_delete=can_delete_persona(editor, persona, db_session),
        holds_add_agents=holds_add_agents,
        is_manage_agents_admin=has_global_permission(editor, Permission.MANAGE_AGENTS),
        is_full_admin=has_global_permission(editor, Permission.FULL_ADMIN_PANEL_ACCESS),
    )
    assert tags["share"] is True  # editable is enough to share (no ADD_AGENTS needed)
    assert (
        tags["edit"] is True
    )  # ...and to edit — both routes gate on editable, not ADD_AGENTS


def test_persona_publish_projection_is_owner_not_add_agents(
    enable_ee: None,  # noqa: ARG001 -- side-effect fixture: forces EE for the whole test
    db_session: Session,
) -> None:
    """publish (org-wide public, via the share route's is_owner_or_admin gate) is owner-or-admin,
    NOT ADD_AGENTS-gated. An owner without ADD_AGENTS can publish but cannot delete (delete's
    route requires ADD_AGENTS). enable_ee because CE auto-grants ADD_AGENTS, masking this."""
    owner = create_test_user(db_session, "publish-owner")
    owner.effective_permissions = []
    db_session.commit()

    persona = _make_persona(db_session, owner=owner, is_public=False, groups=[])
    is_editable = is_persona_editable_by_user(db_session, persona.id, owner)
    holds_add_agents = (
        has_permission(owner, Permission.ADD_AGENTS) is not PermissionAuthority.NONE
    )
    assert holds_add_agents is False  # owner holds no ADD_AGENTS authority under EE

    tags = persona_permissions(
        can_edit=can_edit_persona(owner, persona, db_session, is_editable=is_editable),
        can_share=is_editable,
        can_view_stats=can_view_persona_stats(owner, persona),
        can_delete=can_delete_persona(owner, persona, db_session),
        holds_add_agents=holds_add_agents,
        is_manage_agents_admin=has_global_permission(owner, Permission.MANAGE_AGENTS),
        is_full_admin=has_global_permission(owner, Permission.FULL_ADMIN_PANEL_ACCESS),
    )
    assert (
        tags["publish"] is True
    )  # owner may publish via the share route (no ADD_AGENTS)
    assert tags["delete"] is False  # ...but delete's route requires ADD_AGENTS


def test_document_set_projection_matches_gates(db_session: Session) -> None:
    """edit tracks the editable filter, which equals the within_scope decision the write
    guard enforces; delete/publish track global MANAGE_DOCUMENT_SETS."""
    managed = _make_group(db_session)

    in_scope = create_test_user(db_session, "b-ds-in")
    _manage(db_session, in_scope, managed)
    in_scope.effective_permissions = []

    out_scope = create_test_user(db_session, "b-ds-out")
    _manage(db_session, out_scope, _make_group(db_session))
    out_scope.effective_permissions = []

    admin = create_test_user(db_session, "b-ds-admin", is_admin=True)
    db_session.commit()

    doc_set = _make_doc_set(db_session, is_public=False, groups=[managed])

    for actor in (in_scope, out_scope, admin):
        editable_ids = {
            ds.id
            for ds in fetch_all_document_sets_for_user(
                db_session=db_session, user=actor, get_editable=True
            )
        }
        is_editable = doc_set.id in editable_ids
        # the editable filter equals the write guard's scope decision
        scope_decision = within_scope(
            actor,
            db_session,
            permission=Permission.MANAGE_DOCUMENT_SETS,
            current_group_ids=[managed.id],
            requested_group_ids=[managed.id],
            is_non_public=True,
        )
        assert is_editable == scope_decision, actor.email

        is_ds_admin = has_global_permission(actor, Permission.MANAGE_DOCUMENT_SETS)
        tags = document_set_permissions(
            is_editable=is_editable, is_document_sets_admin=is_ds_admin
        )
        assert tags["edit"] == scope_decision
        assert tags["manage_access"] == scope_decision
        assert tags["delete"] == is_ds_admin


def test_persona_and_doc_set_key_coverage() -> None:
    persona_keys = set(
        persona_permissions(
            can_edit=True,
            can_share=True,
            can_view_stats=True,
            can_delete=True,
            holds_add_agents=True,
            is_manage_agents_admin=True,
            is_full_admin=True,
        )
    )
    assert persona_keys == set(PERSONA_ACTIONS)
    ds_keys = set(
        document_set_permissions(is_editable=True, is_document_sets_admin=True)
    )
    assert ds_keys == set(DOCUMENT_SET_ACTIONS)


def _make_tool(
    db_session: Session,
    *,
    creator: User | None = None,
    in_code: str | None = None,
    mcp_server_id: int | None = None,
) -> Tool:
    tool = Tool(
        name=f"proj-tool-{uuid4().hex[:12]}",
        description="contract",
        user_id=creator.id if creator else None,
        in_code_tool_id=in_code,
        mcp_server_id=mcp_server_id,
    )
    db_session.add(tool)
    db_session.flush()
    return tool


def _make_mcp_server(db_session: Session, *, owner_email: str) -> MCPServer:
    server = MCPServer(
        name=f"proj-mcp-{uuid4().hex[:12]}",
        owner=owner_email,
        server_url="https://mcp.example.com",
        status=MCPServerStatus.CONNECTED,
    )
    db_session.add(server)
    db_session.flush()
    return server


def _link_persona_tool(db_session: Session, persona: Persona, tool: Tool) -> None:
    db_session.add(Persona__Tool(persona_id=persona.id, tool_id=tool.id))
    db_session.commit()


def _make_skill(
    db_session: Session, *, is_public: bool, groups: list[UserGroup]
) -> Skill:
    skill = Skill(
        id=uuid4(),
        slug=f"proj-skill-{uuid4().hex[:12]}",
        name="contract skill",
        description="contract",
        # custom skills need a bundle source (ck_skill_definition_source)
        bundle_file_id=f"proj-bundle-{uuid4().hex}",
        bundle_sha256="0" * 64,
        is_public=is_public,
    )
    db_session.add(skill)
    db_session.flush()
    for group in groups:
        db_session.add(Skill__UserGroup(skill_id=skill.id, user_group_id=group.id))
    db_session.commit()
    return skill


def test_tool_projection_matches_gates(db_session: Session) -> None:
    """Every action affordance (edit, delete, toggle, authenticate) is owner-or-admin, pinned
    to _get_manageable_custom_tool. The creator fully controls the action they made; a scoped
    manager whose group the action is connected to may view/create but not manage it."""
    managed = _make_group(db_session)

    in_scope = create_test_user(db_session, "proj-tool-in")
    _manage(db_session, in_scope, managed)
    in_scope.effective_permissions = []

    # scoped manager who owns the action (via a group unrelated to the action's agents)
    creator = create_test_user(db_session, "proj-tool-creator")
    _manage(db_session, creator, _make_group(db_session))
    creator.effective_permissions = []

    admin = create_test_user(db_session, "proj-tool-admin", is_admin=True)
    db_session.commit()

    tool = _make_tool(db_session, creator=creator)
    # a private agent in the managed group references the action -> connected to `managed`
    persona = _make_persona(
        db_session, owner=creator, is_public=False, groups=[managed]
    )
    _link_persona_tool(db_session, persona, tool)

    for actor in (in_scope, creator, admin):
        manage_enforced = not _guard_raises(
            _get_manageable_custom_tool, tool.id, db_session, actor
        )
        can_manage = can_manage_own_tool(actor, tool)
        assert can_manage == manage_enforced, actor.email
        assert tool_permissions(can_manage=can_manage) == {
            "edit": manage_enforced,
            "delete": manage_enforced,
            "toggle": manage_enforced,
            "authenticate": manage_enforced,
        }

    # a manager of the action's connected group can't manage it (only creator/admin can)
    assert tool_permissions(can_manage=can_manage_own_tool(in_scope, tool)) == {
        "edit": False,
        "delete": False,
        "toggle": False,
        "authenticate": False,
    }
    # the creator fully controls the action they made
    assert tool_permissions(can_manage=can_manage_own_tool(creator, tool)) == {
        "edit": True,
        "delete": True,
        "toggle": True,
        "authenticate": True,
    }


def test_mcp_projection_matches_gates(db_session: Session) -> None:
    """Every MCP action affordance is owner-or-admin, pinned to
    _ensure_mcp_server_owner_or_admin. A scoped manager whose group the server is connected to
    may view it (_ensure_mcp_server_viewable) but not manage it."""
    managed = _make_group(db_session)

    in_scope = create_test_user(db_session, "proj-mcp-in")
    _manage(db_session, in_scope, managed)
    in_scope.effective_permissions = []

    owner = create_test_user(db_session, "proj-mcp-owner")
    _manage(db_session, owner, _make_group(db_session))
    owner.effective_permissions = []

    admin = create_test_user(db_session, "proj-mcp-admin", is_admin=True)
    db_session.commit()

    server = _make_mcp_server(db_session, owner_email=owner.email)
    tool = _make_tool(db_session, mcp_server_id=server.id)
    persona = _make_persona(db_session, owner=owner, is_public=False, groups=[managed])
    _link_persona_tool(db_session, persona, tool)

    for actor in (in_scope, owner, admin):
        manage_enforced = not _guard_raises(
            _ensure_mcp_server_owner_or_admin, server, actor
        )
        can_manage = can_manage_mcp_server(actor, server)
        assert can_manage == manage_enforced, actor.email
        assert mcp_server_permissions(can_manage=can_manage) == {
            "edit": manage_enforced,
            "delete": manage_enforced,
            "authenticate": manage_enforced,
            "manage_status": manage_enforced,
        }

    # a manager of the server's connected group may VIEW but not manage it
    assert not _guard_raises(_ensure_mcp_server_viewable, server, in_scope, db_session)
    assert can_manage_mcp_server(in_scope, server) is False
    # the owner fully manages their server
    assert mcp_server_permissions(can_manage=can_manage_mcp_server(owner, server)) == {
        "edit": True,
        "delete": True,
        "authenticate": True,
        "manage_status": True,
    }


def test_skill_projection_matches_gates(db_session: Session) -> None:
    """edit/manage_access track the assert_within_scope guard on the skill's groups;
    delete is FULL_ADMIN; publish (make public) is global MANAGE_SKILLS. A scoped manager
    edits/re-grants a managed skill but can never delete or publish it."""
    managed = _make_group(db_session)

    in_scope = create_test_user(db_session, "proj-skill-in")
    _manage(db_session, in_scope, managed)
    in_scope.effective_permissions = []

    out_scope = create_test_user(db_session, "proj-skill-out")
    _manage(db_session, out_scope, _make_group(db_session))
    out_scope.effective_permissions = []

    admin = create_test_user(db_session, "proj-skill-admin", is_admin=True)
    db_session.commit()

    skill = _make_skill(db_session, is_public=False, groups=[managed])
    group_ids = get_group_ids_for_skill(skill.id, db_session)

    for actor in (in_scope, out_scope, admin):
        edit_enforced = not _guard_raises(
            assert_within_scope,
            actor,
            db_session,
            permission=Permission.MANAGE_SKILLS,
            current_group_ids=group_ids,
            requested_group_ids=group_ids,
            is_non_public=not skill.is_public,
        )
        # publish drives the same guard with the requested public state
        publish_enforced = not _guard_raises(
            assert_within_scope,
            actor,
            db_session,
            permission=Permission.MANAGE_SKILLS,
            current_group_ids=group_ids,
            requested_group_ids=group_ids,
            is_non_public=False,
        )
        can_edit = within_scope(
            actor,
            db_session,
            permission=Permission.MANAGE_SKILLS,
            current_group_ids=group_ids,
            requested_group_ids=group_ids,
            is_non_public=not skill.is_public,
        )
        assert can_edit == edit_enforced, actor.email
        is_full_admin = has_global_permission(actor, Permission.FULL_ADMIN_PANEL_ACCESS)
        is_skills_admin = has_global_permission(actor, Permission.MANAGE_SKILLS)
        tags = custom_skill_permissions(
            can_edit=can_edit,
            is_full_admin=is_full_admin,
            is_skills_admin=is_skills_admin,
        )
        assert tags["edit"] == edit_enforced
        assert tags["manage_access"] == edit_enforced
        assert tags["delete"] == is_full_admin
        assert tags["publish"] == publish_enforced  # global MANAGE_SKILLS

    # in-scope manager edits/re-grants but can't delete or publish
    assert custom_skill_permissions(
        can_edit=within_scope(
            in_scope,
            db_session,
            permission=Permission.MANAGE_SKILLS,
            current_group_ids=group_ids,
            requested_group_ids=group_ids,
            is_non_public=not skill.is_public,
        ),
        is_full_admin=has_global_permission(
            in_scope, Permission.FULL_ADMIN_PANEL_ACCESS
        ),
        is_skills_admin=has_global_permission(in_scope, Permission.MANAGE_SKILLS),
    ) == {"edit": True, "manage_access": True, "delete": False, "publish": False}


def test_actions_and_skill_key_coverage() -> None:
    assert set(tool_permissions(can_manage=True)) == set(TOOL_ACTIONS)
    assert set(mcp_server_permissions(can_manage=True)) == set(MCP_SERVER_ACTIONS)
    assert set(
        custom_skill_permissions(
            can_edit=True, is_full_admin=True, is_skills_admin=True
        )
    ) == set(CUSTOM_SKILL_ACTIONS)


def test_user_group_projection_matches_gates(db_session: Session) -> None:
    """Each flag is pinned to its real route, not the bool that built it: manage and
    edit_token_limits → assert_manages_group (per-group scoped — the token read route now
    admits scope), delete → delete-group (global MANAGE_USER_GROUPS), edit_permissions →
    permission-toggle (FULL_ADMIN). groups_admin (global MANAGE_USER_GROUPS, not full admin)
    separates the two levels; out_scope (manages a different group) pins the per-group gate."""
    managed = _make_group(db_session)

    in_scope = create_test_user(db_session, "proj-ug-in")
    _manage(db_session, in_scope, managed)
    in_scope.effective_permissions = []

    out_scope = create_test_user(db_session, "proj-ug-out")
    _manage(db_session, out_scope, _make_group(db_session))
    out_scope.effective_permissions = []

    groups_admin = create_test_user(db_session, "proj-ug-groupsadmin")
    groups_admin.effective_permissions = [Permission.MANAGE_USER_GROUPS.value]

    admin = create_test_user(db_session, "proj-ug-admin", is_admin=True)
    db_session.commit()

    for actor in (in_scope, out_scope, groups_admin, admin):
        manage_enforced = not _guard_raises(
            assert_manages_group, actor, db_session, group_id=managed.id
        )
        # the token-limit POST guard (scoped create) is the same managed-scope decision
        token_create_enforced = not _guard_raises(
            assert_within_scope,
            actor,
            db_session,
            permission=Permission.MANAGE_USER_GROUPS,
            current_group_ids=[managed.id],
            requested_group_ids=[managed.id],
            is_non_public=True,
        )
        can_manage = manages_group(actor, db_session, group_id=managed.id)
        assert can_manage == manage_enforced, actor.email
        assert can_manage == token_create_enforced, actor.email

        tags = user_group_permissions(
            can_manage=can_manage,
            is_user_groups_admin=has_global_permission(
                actor, Permission.MANAGE_USER_GROUPS
            ),
            is_full_admin=has_global_permission(
                actor, Permission.FULL_ADMIN_PANEL_ACCESS
            ),
        )
        assert tags["manage"] == manage_enforced, actor.email
        assert tags["delete"] == _route_admits(delete_user_group, "_", actor), (
            actor.email
        )
        assert tags["edit_permissions"] == _route_admits(
            set_user_group_permissions, "user", actor
        ), actor.email
        # edit_token_limits rides the token read route: GATE 1 admits scope, GATE 2 is
        # assert_manages_group — net per-group decision, so AND the two.
        token_read_gate1 = _route_admits(get_group_token_limit_settings, "user", actor)
        assert tags["edit_token_limits"] == (token_read_gate1 and manage_enforced), (
            actor.email
        )

    assert user_group_permissions(
        can_manage=manages_group(in_scope, db_session, group_id=managed.id),
        is_user_groups_admin=has_global_permission(
            in_scope, Permission.MANAGE_USER_GROUPS
        ),
        is_full_admin=has_global_permission(
            in_scope, Permission.FULL_ADMIN_PANEL_ACCESS
        ),
    ) == {
        "manage": True,
        "delete": False,
        "edit_permissions": False,
        # scoped manager now fully manages its group's token limits
        "edit_token_limits": True,
    }

    # groups_admin (global MANAGE_USER_GROUPS, not full admin): manages token limits and
    # deletes the group, but can't edit permissions (FULL_ADMIN).
    assert user_group_permissions(
        can_manage=manages_group(groups_admin, db_session, group_id=managed.id),
        is_user_groups_admin=has_global_permission(
            groups_admin, Permission.MANAGE_USER_GROUPS
        ),
        is_full_admin=has_global_permission(
            groups_admin, Permission.FULL_ADMIN_PANEL_ACCESS
        ),
    ) == {
        "manage": True,
        "delete": True,
        "edit_permissions": False,
        "edit_token_limits": True,
    }


def test_user_group_key_coverage() -> None:
    assert set(
        user_group_permissions(
            can_manage=True, is_user_groups_admin=True, is_full_admin=True
        )
    ) == set(USER_GROUP_ACTIONS)


def test_group_token_rate_limit_write_scope(db_session: Session) -> None:
    """A group token-limit write needs the caller to manage the group AND the limit to
    belong to it — so a group admin fully manages its limits, but a global/per-user limit or
    another group's limit can't be reached through the group path."""
    managed = _make_group(db_session)
    other = _make_group(db_session)

    args = TokenRateLimitArgs(enabled=True, token_budget=1000, period_hours=24)
    managed_limit = insert_user_group_token_rate_limit(
        db_session=db_session, token_rate_limit_settings=args, group_id=managed.id
    )
    global_limit = insert_global_token_rate_limit(db_session, args)

    in_scope = create_test_user(db_session, "proj-trl-in")
    _manage(db_session, in_scope, managed)
    in_scope.effective_permissions = []

    out_scope = create_test_user(db_session, "proj-trl-out")
    _manage(db_session, out_scope, other)
    out_scope.effective_permissions = []

    groups_admin = create_test_user(db_session, "proj-trl-groupsadmin")
    groups_admin.effective_permissions = [Permission.MANAGE_USER_GROUPS.value]

    admin = create_test_user(db_session, "proj-trl-admin", is_admin=True)

    plain = create_test_user(db_session, "proj-trl-plain")
    plain.effective_permissions = []
    db_session.commit()

    def denied(actor: User, group_id: int, rate_limit_id: int) -> bool:
        return _guard_raises(
            _authorize_group_token_rate_limit_write,
            actor,
            db_session,
            group_id=group_id,
            rate_limit_id=rate_limit_id,
        )

    assert not denied(admin, managed.id, managed_limit.id)
    assert not denied(groups_admin, managed.id, managed_limit.id)
    assert not denied(in_scope, managed.id, managed_limit.id)
    assert denied(out_scope, managed.id, managed_limit.id)
    assert denied(plain, managed.id, managed_limit.id)

    # a global limit can't be reached through the group path — even for a full admin
    assert denied(admin, managed.id, global_limit.id)

    # the limit must belong to the claimed group (can't reach managed's limit via other)
    assert denied(out_scope, other.id, managed_limit.id)
    assert denied(in_scope, other.id, managed_limit.id)

    # an unknown id folds into the same OnyxError 404, not the helper's raw ValueError
    nonexistent_limit_id = -1
    assert denied(in_scope, managed.id, nonexistent_limit_id)
    assert denied(admin, managed.id, nonexistent_limit_id)
