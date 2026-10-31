# Authorization

> What an identity may do. Group grants and group-manager scope decide which
> routes a user, service account or token can reach and which resources a
> route lets them change.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE has the `Permission` model, `require_permission`, PAT scopes
and a fixed set of ungated permissions for every signed-in user. EE adds the
group admin API: permission grants on groups and group managers.

---

## User experience

- **An admin** gives capabilities to user groups, such as "manage connectors"
  or full admin. There is no per-user role. A user holds the union of the
  grants of every group they belong to. A change applies on the user's next
  request.
- **An admin** can make a user the manager of a group. The manager then gets
  admin rights inside that group only: they can change the private connectors,
  document sets, agents, skills and members that belong only to groups they
  manage. They cannot make a resource public or touch a resource that is also
  in a group they do not manage.
- **A developer or script** with a scoped PAT reaches only the routes its
  scopes cover. A PAT without scopes acts with all of its owner's permissions.
- **When access is denied,** the API returns 403 `INSUFFICIENT_PERMISSIONS`.
  The detail text tells which check refused. The UI hides the controls the
  user cannot use, so a denial in the UI usually means the projection and the
  guard disagree.

---

## Scope

This component owns route authorization and the permission model: the
`Permission` values and their implications, group grants and their stored
projection on `User`, group-manager scope (GATE 1 and GATE 2), the list of PAT
scopes a user can pick and the cap they put on a request, and the read-side
permission map the UI uses to hide controls.

Neighbours own:
- [[auth-and-identity]]: who the caller is, and the credential that carries
  the PAT scopes.
- [[access-control]]: which documents a user can retrieve. Permissions decide
  who may administer a connector or document set, not who sees its documents.
- [[editions-and-gating]]: CE versus EE dispatch and the tier of each PAT
  scope.
- The resource components ([[cc-pairs-and-creds]], [[agents-personas]],
  [[skills]], [[mcp-and-custom-tools]]): the GATE 2 call inside each handler,
  and resource rules other than group scope, such as editor shares.

---

## Architecture

**Three answers.** `onyx/auth/permissions.py:has_permission` classifies a
user's authority for one permission:

```
GLOBAL  the permission is in get_effective_permissions(user)
        (granted + implied; FULL_ADMIN_PANEL_ACCESS gives every permission;
         CE adds CE_UNGATED_PERMISSIONS for every non-anonymous user)
SCOPED  user.is_group_manager and the permission is in
        SCOPED_MANAGER_PERMISSIONS_EXPANDED (the bundle and its implied reads)
NONE    otherwise
```

**Two gates.** `require_permission(required, allow_scope=..., allow_anonymous=...)`
is the route dependency (GATE 1). By default it admits GLOBAL only.
`allow_scope=True` also admits SCOPED. The handler must then limit a scoped
manager to the groups they manage (GATE 2):

```
writes          onyx/auth/scoped_permissions.py:assert_within_scope
                  every current and requested group is managed, at least one
                  group, and the resource is not public
one group       assert_manages_group (membership, manager, group settings)
reads           db/scoped_permissions.py:within_managed_scope_clause
```

A scoped manager's groups come from `scoped_group_ids_subquery`, read live on
each check. Default groups (Basic and Admin) never count as managed.

**Token cap.** `require_permission` also reads `request.state.token_scopes`,
which [[auth-and-identity]] sets for a PAT. The required permission must be
implied by the token's scopes as well as held by the user. Before that,
`onyx/auth/users.py:_scoped_pat_permitted_on_route` refuses a scoped PAT on a
route that has neither `require_permission` nor `scope_exempt`.

**Storage.** `PermissionGrant` rows on groups are the source.
`db/permissions.py:recompute_user_permissions__no_commit` writes the union of a
user's grants to `User.effective_permissions` and refreshes
`User.is_group_manager`. Implied permissions expand at read time only. A
service account in no group gets `WRITE_CHAT` from `account_derived_permissions`.

**Projection.** `onyx/auth/permission_projection.py` stamps a per-resource map,
such as `edit`, `delete` and `publish`, on resource DTOs. `/me` returns
`admin_capabilities` for admin navigation. Both only show or hide controls;
the guards decide.

---

## Contracts and traps

1. `every-route-has-auth-dependency` **Every route needs a known auth
   dependency.** `onyx/server/auth_check.py:check_router_auth` runs at startup and
   raises for a route with no user dependency, no `require_permission` and no
   `PUBLIC_ENDPOINT_SPECS` entry. EE extends the public list in
   `ee/onyx/server/auth_check.py`. A new dependency type must be added to that
   check, or every route that uses it fails startup.
2. `allow-scope-is-reach-only` **`allow_scope=True` gives reach, not
   authority.** A route with `allow_scope=True` and no GATE 2 check gives every
   group manager global access to that resource type. Read routes need GATE 2
   too, or they return all rows. Group create, group delete and the
   group-permission route stay GLOBAL only. False leads: the
   `require_permission` docstring says "never on delete", but
   `server/features/persona/api.py:delete_persona`,
   `server/manage/administrative.py:create_deletion_attempt_for_connector_id`
   and `server/features/document_set/api.py:delete_document_set` set
   `allow_scope` on purpose and decide in the handler.
   `onyx/auth/scoped_permissions.py:assert_global` has no callers.
3. `gate2-uses-stored-groups` **GATE 2 for an update takes the current groups
   from the database.** Pass the stored groups as `current_group_ids` and the
   request's groups as `requested_group_ids`. Group ids from the client would
   let a manager move a resource out of scope. Call
   `onyx/auth/scoped_permissions.py:assert_within_scope`
   before any broad `try/except`, or its 403 becomes a 500.
4. `managers-never-publish` **Manager scope never covers a public resource.**
   `onyx/auth/scoped_permissions.py:within_scope` refuses a SCOPED caller when `is_non_public` is false. The
   caller computes the flag. For connectors, document sets and skills it is
   true only when the stored and the requested state are both non-public, so a
   manager can neither publish nor pull in a public resource. Agents pass the
   stored state only (`db/persona.py`), because the owner may publish their own
   agent. Managing a default group gives no scope, because the Basic group
   holds every user. A perm-synced pair with no manage groups skips GATE 2
   (`onyx/server/documents/cc_pair.py:authorize_pairing`,
   `server/documents/connector_edit.py:_authorize_proposed_state`): its ACL
   comes from the source, so no group bounds who reads it.
5. `scoped-manager-rights` **Who may edit, delete and publish differs by
   resource.** The handlers below enforce it. Check this table before you add or change a delete or publish route.

   | Resource | Edit | Delete | Make org-wide public |
   |---|---|---|---|
   | Connector (cc-pair) | EDIT access: global `MANAGE_CONNECTORS`, or a manager of a group with the Editor role on the pair; the Operator role gives only OPERATE ([[cc-pairs-and-creds]]) | Same as edit | Global `MANAGE_CONNECTORS` |
   | Agent | Owner or editor share; a change to its groups also needs GATE 2 on `MANAGE_AGENTS` | Owner, owner-group member, or global `MANAGE_AGENTS`, and `ADD_AGENTS` (scope admits); not a manager (`onyx/db/persona.py:can_delete_persona`) | Same people as delete, without `ADD_AGENTS` (`onyx/db/persona.py:update_persona_public_status`) |
   | Document set | Global, manager scope, or the creator of a private set with no groups | Global `MANAGE_DOCUMENT_SETS`, or the creator of a private set with no groups | Global `MANAGE_DOCUMENT_SETS` |
   | Custom skill | Owner, editor share, manager scope, or global `MANAGE_SKILLS` | Any editor; a required skill needs full admin (`server/features/skill/api.py:delete_current_user_skill`) | Owner or global `MANAGE_SKILLS` (`server/features/skill/api.py:_ensure_can_edit_org_visibility`) |
   | Custom action, MCP server | Owner or global `MANAGE_ACTIONS` (`db/tools.py:can_manage_tool`) | Same as edit | Not applicable |
   | User group | Manager of that group, or global `MANAGE_USER_GROUPS` | Global `MANAGE_USER_GROUPS`; never a default group | Grants: full admin only |
6. `recompute-on-grant-change` **Every change to grants or membership must
   recompute permissions.** `effective_permissions` and `is_group_manager` are
   stored copies. A new write path that changes `PermissionGrant` or
   `User__UserGroup` must call
   `db/permissions.py:recompute_user_permissions__no_commit` or
   `db/permissions.py:recompute_permissions_for_group__no_commit`, or the user keeps the old
   rights.
7. `no-privilege-amplification` **Adding a member must not raise the actor's
   own power.** `ee/onyx/db/user_group.py:_assert_no_privilege_amplification`
   blocks a `MANAGE_USER_GROUPS` holder from adding anyone to a group whose
   grants they do not hold, such as the seeded Admin group. In the same way,
   adding or removing an agent's group share is a `MANAGE_AGENTS` action
   (`ee/onyx/db/persona.py:_assert_group_share_within_scope`), and changing a
   skill's group shares is a `MANAGE_SKILLS` action.
8. `scoped-pat-fails-closed` **A scoped PAT fails closed; an unscoped PAT does
   not.** A scoped PAT reaches only routes with `require_permission` or
   `scope_exempt()`, and only when its scopes imply the required permission. A
   PAT whose `scopes` is `None` acts with all of its owner's permissions on
   every route. A new route that a scoped token must reach needs one of the two
   dependencies. `onyx/auth/users.py:_scoped_pat_permitted_on_route` reads only
   the route's direct dependencies. A `require_permission` inside a wrapper
   dependency, such as `ee/onyx/auth/users.py:current_cloud_superuser`, does
   not count: every scoped PAT gets a 403 on that route, and an unscoped PAT
   passes.
9. `anonymous-stays-on-chat` **Anonymous access stays on chat routes.**
   `onyx/auth/users.py:get_anonymous_user` holds only `BASIC_ACCESS` and gets no
   CE ungated permissions. Over HTTP it is reachable only through
   `current_chat_accessible_user`, as a direct dependency or through
   `require_permission(..., allow_anonymous=True)`. List those routes with
   `git grep -n "current_chat_accessible_user\|allow_anonymous=True"`. A new
   route that uses either needs a security review. Anonymous,
   service-account and bot identities are real `User` objects, so "no session"
   does not mean "no user".
10. `projection-mirrors-guard` **The UI permission map must match the write
    guard.** Each builder in `auth/permission_projection.py` and its docstring
    must state the same decision as the route. A new guard needs its
    projection key and a case in
    `backend/tests/external_dependency_unit/auth/test_permission_projection_contract.py`.
    The test drives the guard helpers and some handlers, not every route, so a
    route that stops calling its helper can drift without a failure.
11. `user-role-is-dead` **`User.role` is not authority.** No code reads or
    writes it; `UserRole` (`auth/schemas.py`) is only its column type. Use
    `auth/permissions.py:has_permission`, or
    `auth/permissions.py:has_global_permission` to exclude scoped managers.
    "Curator" means `is_group_manager` plus the scoped bundle.
12. `create-api-keys-gates-consent` **`CREATE_USER_API_KEYS` gates both PAT
    creation and OAuth-provider consent** (`server/pat/api.py:create_token`,
    `server/oauth_provider/api.py`). It is the only grant an admin can switch
    on the seeded Basic group (`auth/permissions.py:DEFAULT_GROUP_TOGGLEABLE_PERMISSIONS`),
    so one toggle stops users from minting PATs and from approving third-party
    apps. `db/oauth_provider.py:create_oauth_provider_grant__no_commit`
    checks it again when it issues the grant. A new way for a user to mint a
    credential for themselves needs the same permission.

---

## Decisions

- **Group grants instead of user roles.** Capabilities come from
  `PermissionGrant` rows on groups, so an IdP that syncs group membership
  through SCIM also decides capability. The granted set is stored on `User`,
  so every auth query loads it with no join. The same `Permission` values scope
  PATs, so one check (`require_permission`) covers users and tokens.
- **Scope is never stored.** The scoped bundle is not written to
  `effective_permissions`, and managed groups are read live. A group rename,
  delete or manager change cannot leave a stale scope.

---

## Known issues

- **The custom-skill projection disagrees with the routes.**
  `onyx/auth/permission_projection.py:custom_skill_permissions` says delete is full
  admin only and publish is global `MANAGE_SKILLS` only. The routes let any
  editor delete a skill that is not required, and let the owner publish. No
  route calls this builder, so it affects only its contract test.
- **API-key creation may be admin-equivalent.** An earlier audit reported that
  `create_api_key` does not cap `group_ids`, so a holder of
  `MANAGE_SERVICE_ACCOUNT_API_KEYS` can put a key in the Admin group. The
  `server/api_key/` files were not readable during this verification. A person
  with access must confirm it and, if it is by design, move it to Decisions.

---

## Dependencies

- [[auth-and-identity]]: resolves the `User` and sets the PAT scopes on the
  request.
- [[editions-and-gating]]: `global_version` selects the CE ungated
  permissions; tier checks gate PAT scopes.

---

## Recipes

- `new-permission` **Add a permission.** Copy `MANAGE_ACTIONS` in `Permission`
  (`db/enums.py`); list its uses with `git grep -n MANAGE_ACTIONS -- backend web/src`.
  Decide its `IMPLIED_PERMISSIONS` entry, whether it is in
  `PERMISSION_REGISTRY` or `NON_TOGGLEABLE_PERMISSIONS`, and whether it joins
  `SCOPED_MANAGER_PERMISSIONS`. If it is scoped, add GATE 2 at every write
  site ([[#allow-scope-is-reach-only]]) and a projection key
  ([[#projection-mirrors-guard]]). On CE no group-permission UI exists, so a
  new gated permission reaches only admins unless it joins
  `auth/permissions.py:CE_UNGATED_PERMISSIONS`. This recipe gives a group
  grant, not a token scope ([[#new-pat-scope]]).
- `new-pat-scope` **Add a PAT scope for a route.** Copy `READ_SEARCH` or `USE_LLM_GATEWAY`,
  not `MANAGE_ACTIONS`. Put the new value in `Permission.IMPLIED`
  (`db/enums.py`), because no grant stores it. Add it to the `BASIC_ACCESS`
  entry of `IMPLIED_PERMISSIONS`, and to `CRAFT_SANDBOX` if Craft sandboxes
  must reach the route, so users hold it. Add a `PatScopeOption` to
  `server/pat/models.py:_ASSIGNABLE_SCOPES`, with `min_tier` if it is paid;
  `server/pat/api.py` rejects scopes outside `SELECTABLE_PAT_SCOPES`, and the
  token form reads the list from `list_selectable_scopes`. Put
  `require_permission(Permission.X)` directly on the route
  ([[#scoped-pat-fails-closed]]). To reuse an existing scope, do only the last
  step. An OAuth-provider token carries only `READ_SEARCH`, so an MCP tool can
  call the route only when it stays on `READ_SEARCH`
  ([[mcp-server#oauth-token-route-allowlist]]).
- `scoped-manager-route` **Add a route that group managers can use.** Copy
  `server/manage/administrative.py:create_deletion_attempt_for_connector_id`:
  `allow_scope=True` at GATE 1, then the resource lookup that applies the
  manager's scope. List the current scoped routes with
  `git grep -n "allow_scope=True" -- backend`. Check the matrix in
  [[#scoped-manager-rights]] for delete and publish.
- `investigate-403` **Investigate a 403.** Read the `detail` of the response.
  `backend/tests/integration/tests/permissions/_access_matrix.py:gate_of` maps
  each detail prefix to GATE 1, GATE 2, admin only or a handler check. A GATE 1
  denial of a manager means the route has no `allow_scope`; a GATE 2 denial
  means the scope check worked. GATE 2 denials also emit a
  `PERMISSION_DENIED` audit event with the gate name. For a PAT, check its
  scopes first ([[#scoped-pat-fails-closed]]).
- `setup-scoped-manager` **Set up a scoped manager for a test.** On an EE build, create a group with
  `UserGroupManager.create`, attach the resource to it, add the user, then call
  `UserGroupManager.set_manager`
  (`backend/tests/integration/common_utils/managers/user_group.py`). Do not
  make the user a manager of Basic or Admin; that gives no scope.

---

## Verification

- Integration suites under `backend/tests/integration/tests/`: `permissions/`,
  `permissions_access/`, `permissions_membership/`, `permissions_resources/`,
  `pat/` and `usergroup/`. `backend/tests/integration/tests/permissions/_access_matrix.py` is the shared
  harness: it calls an endpoint as each actor and classifies the 403 gate.
- External dependencies: `backend/tests/external_dependency_unit/auth/`
  (scoped permissions and the projection contract).
- Unit: `backend/tests/unit/onyx/auth/` (the scoped PAT route gate).
  `backend/tests/unit/onyx/server/test_route_contract.py` pins the gate of
  every route in a manifest beside it; after you add or re-gate a
  route, run it with `ONYX_UPDATE_ROUTE_MANIFEST=1`. It also fails a new
  `allow_scope=True` handler that reaches no GATE 2 helper, and a GET that
  commits. Its baseline of old violations can only shrink.
- By hand: give a non-admin a group with a private connector and make them its
  manager. Confirm they can edit that connector, cannot make it public, and
  cannot edit a connector that is also in another group.
