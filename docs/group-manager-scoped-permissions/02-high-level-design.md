> Status: active · Task: group-manager-scoped-permissions

# §8 Scoped Permissions (Group Manager) — High-Level Design

## What we're building, in one paragraph

The base system (§1–7) grants permission tokens to a whole **group** — every member gets them, **everywhere**.
A **Group Manager** is the controlled exception: one user given admin-like control over a **single group's**
resources and members, and *nothing* outside it. We add this with **one boolean** (`is_manager` on the
membership row), **one code-defined permission bundle** (`SCOPED_MANAGER_PERMISSIONS`), **live** scope
resolution (never cached, never stale), and a **two-gate** enforcement model whose authoritative check runs
*inside the database write*, not at the route. No new tables, no new rows, no second auth round-trip.

## The core idea: scope lives on the membership edge, abilities live in code

```
                 user__user_group (the membership EDGE)
   ┌───────┐   ┌───────────────────────────────────┐   ┌────────────┐
   │ Alice │──▶│ user_id=Alice  group_id=Engineering│──▶│ Engineering│
   └───────┘   │ is_manager = TRUE  ◀── the only new │   │  (group)   │
               │                       bit of state  │   └────────────┘
               └───────────────────────────────────┘
                                │
            is_manager=TRUE  ⇒  apply SCOPED_MANAGER_PERMISSIONS (in code)
                                │   {manage:connectors, manage:document_sets,
                                ▼    manage:agents, add:agents,
                          but ONLY to    manage:user_groups, manage:actions}
                          Engineering's resources — resolved LIVE
```

Two things never live in the database as data:
- **The manager's abilities** are a constant set in code (`SCOPED_MANAGER_PERMISSIONS`), *not* rows in
  `permission_grant`. `permission_grant` stays **global-only**. (A role binding ≠ a permission — the same split
  k8s, AWS IAM, and Zanzibar make.)
- **The manager's scope** (which groups) is *not* cached — it is resolved live from `is_manager` on every
  request that needs it (`get_scoped_groups`). One indexed read. Because a manager is always a member, and
  membership is the source, the scope can never go stale after a group is renamed, moved, or deleted.

## The two gates — the heart of the design

Every manager action passes **two** independent checks. The first lets them *reach* the code; the second is the
*authorization of record*.

```
  Manager calls  PUT /document-set  {id: 7, groups:[Engineering]}
        │
        ▼
  ┌─────────────────────────── GATE 1: ROUTE GATE ───────────────────────────┐
  │ require_permission(...) → has_permission_or_scope(MANAGE_DOCUMENT_SETS)   │
  │   passes if: holds the token GLOBALLY  OR  manages ANY group.            │
  │   COARSE. Can only reject. Does NOT authorize the action.                │
  └──────────────────────────────────────────────────────────────────────────┘
        │ (reached the handler)
        ▼
  ┌──────────────────── GATE 2: PER-RESOURCE WRITE-SIDE GATE ─────────────────┐
  │ assert_group_set_within_scope(user, resource, new_groups, access_type)    │
  │   runs INSIDE the DB write, in the same transaction. Re-reads the          │
  │   resource's CURRENT groups from the DB (not the client's list). Allows    │
  │   only if the resource ends up:                                            │
  │     • in ≥1 managed group,                                                 │
  │     • with NO group outside the managed set (current ∪ new ⊆ managed),     │
  │     • PRIVATE (never PUBLIC / SYNC).                                        │
  │   Admin override (admin token) skips this entirely.                        │
  └──────────────────────────────────────────────────────────────────────────┘
        │
        ▼
  write commits  (or OnyxError FORBIDDEN)
```

**Why two gates and not one?** The route gate is cheap and coarse — it answers "could this user *ever* do this?"
without knowing the specific resource. It exists so a manager isn't 403'd before the handler can even load the
resource. But it is *not* safe on its own: a manager holds `manage:document_sets` "scopedly," so a global-style
route check would let them edit *any* document set. The real decision needs the resource's actual group
membership, which only the handler/DB layer has — so the authoritative check lives there, re-reading current
state in-transaction. **The route gate can only ever reject; it must never be the thing that authorizes.**

## Why the write-side gate must re-read current groups (the escalation it closes)

The listing filters (`_add_user_filters`) only hide out-of-scope resources from the **UI**. A direct API call by
resource ID bypasses them entirely. And a group-reassign request carries only the *new* groups. So without
re-reading current state, this works:

```
  Finance doc set #7 currently belongs to {Finance}.  Alice manages {Engineering} only.
  Alice calls:  PUT /document-set  {id: 7, groups:[Engineering]}
  Naive check (new groups ⊆ managed):  [Engineering] ⊆ {Engineering}  ✓  → Alice captures Finance's doc set.
  Correct check (CURRENT ∪ new ⊆ managed):  {Finance, Engineering} ⊄ {Engineering}  ✗  → rejected.
```

The gate therefore loads the resource's **current** groups in the same transaction and requires
`current_groups ∪ requested_groups ⊆ managed_groups`. Capture-by-reassignment is closed.

## End-to-end data flow

### Read / list path (which connectors does Alice see in the admin UI?)
1. `current_user` loads Alice with her cached `effective_permissions` (global tokens only).
2. The list endpoint calls `_add_user_filters(stmt, user, get_editable=True)`.
3. Filter logic: `admin` → no filter; else if she holds the token **globally** → all; else if she **manages any
   group** (`get_scoped_groups` non-empty) → resources whose group set ⊆ her managed groups; else → empty
   (`get_editable`) / public+member (viewing). **Fail-closed:** empty managed set ⇒ empty result, never "no
   filter."

### Write path (Alice edits an Engineering connector)
1. Route gate `has_permission_or_scope(MANAGE_CONNECTORS)` → passes (she manages a group).
2. Handler calls the connector update DB fn.
3. **Inside the DB write**, `assert_group_set_within_scope` re-reads the cc_pair's current groups, checks
   `current ∪ requested ⊆ get_scoped_groups(Alice)`, checks `access_type == PRIVATE`. Pass → write; fail →
   `OnyxError(INSUFFICIENT_PERMISSIONS)`, transaction rolls back.

### Membership path (Alice adds Bob to Engineering)
1. Route gate `has_permission_or_scope(MANAGE_USER_GROUPS)` → passes.
2. `add_users_to_user_group(... group_id=Engineering ...)`.
3. Write-side gate: `Engineering ∈ get_scoped_groups(Alice)`? Yes → add. (If Alice targeted Marketing → reject.)
   `set_group_permissions` is **untouched** — it stays `FULL_ADMIN_PANEL_ACCESS`-only, so a manager can never
   change *what tokens* a group grants (no privilege manufacturing).

## Component interaction

```
        ┌────────────────────────── auth/permissions.py ──────────────────────────┐
        │  SCOPED_MANAGER_PERMISSIONS   (code-defined bundle)                       │
        │  get_scoped_groups(user, perm)         → live indexed read of is_manager  │
        │  has_permission_or_scope(user, perm)   → GATE 1 (route)                   │
        │  assert_group_set_within_scope(...)    → GATE 2 (write-side)              │
        └───────▲───────────────▲────────────────────────────▲─────────────────────┘
                │               │                             │
   route deps   │   6× _add_user_filters       group + resource DB write fns
 (require_perm) │   (connector, persona,        (add_users_to_user_group,
                │    document_set, credentials,   update_user_group,
   EE/CE        │    feedback, token_limit)       add_credential_to_connector,
   API routers  │    re-keyed onto                update_document_set,
                │    get_scoped_groups            create_update_persona, …)
                                                  each calls GATE 2 before commit

        ┌──────────────── db/models.py ────────────────┐   ┌─── alembic/versions ───┐
        │ User__UserGroup.is_manager : bool (NEW)       │   │ add is_manager + backfill│
        └───────────────────────────────────────────────┘   └──────────────────────────┘

        ┌──────── make_group_manager / revoke_group_manager ────────┐
        │ one-row flip · used by migration + Group-Manager UI        │
        └────────────────────────────────────────────────────────────┘
```

## End-to-end scenario

> Admin makes **Alice** a manager of **Engineering** (`make_group_manager(Alice, Engineering)` → one row flip,
> `is_manager=true`).

- Alice opens the Connectors page → sees only Engineering's connectors (filter re-keyed on managed groups).
- She creates a connector into Engineering, PRIVATE → GATE 2: `{Engineering} ⊆ {Engineering}` ✓, PRIVATE ✓ →
  created.
- She tries to set it PUBLIC → GATE 2 rejects (managers are PRIVATE-only).
- She tries `PUT /connector/<Finance id> {groups:[Engineering]}` → GATE 2 re-reads current `{Finance}`,
  `{Finance,Engineering} ⊄ {Engineering}` ✗ → 403.
- She adds Bob to Engineering → allowed. She tries to add Bob to Marketing → 403.
- She opens a group's permission editor → cannot change its tokens (`set_group_permissions` stays admin-only).
- She mints a PAT scoped to `manage:connectors` → it works only on Engineering connectors (token caps the
  permission set; `is_manager` still bounds the groups, live). She cannot mint a PAT that widens her to
  Marketing — the group bound comes from her live `is_manager`, which the token cannot touch.

## The decisions that mattered (resolved at GATE 2)

1. **`is_manager` at the route gate → CACHE THE BOOLEAN (D1).** A dedicated cached `user.is_group_manager`
   (recomputed on membership change and on a manager flip; loaded with the user at auth) lets GATE 1 decide
   reachability with **zero queries**, per the wiki §8.1 intent. It is a *sibling* field to
   `effective_permissions` (which stays global-tokens-only) — not a sentinel inside the token list. Crucially,
   only the **boolean** is cached; the managed-group **list** is still resolved live, so the scope set itself
   can never go stale.

2. **GATE 2 lives inside each group/resource DB-write function** (re-reading current groups in-txn), exposed as
   one shared helper `assert_group_set_within_scope`. *Not* a second FastAPI dependency (a dependency can't see
   the resource's current groups or run in the write transaction). The route dependency `has_permission_or_scope`
   is only GATE 1.

3. **PAT composition** — a PAT stays a flat permission cap (`request.state.token_scopes`, already implemented). A
   manager's *group* scope is **not** encoded in the token — it always comes from live `is_manager`. So a PAT
   can only ever **narrow** the manager's permission set and never widen group reach. No new PAT schema; §8.5
   "intersect" = (manager bundle ∩ token scopes) for permissions, AND (live managed groups) for scope, both
   enforced independently.

4. **Group create → admins only (D2).** Managers manage assigned groups; they cannot create top-level groups.
   **Manager assignment → admin or manager-of-that-group (D3)**, enabling in-group delegation.

## What is explicitly out of scope

- Dropping `role` / `UserRole` / `is_curator` and migrating the 3 residual `user.role==ADMIN` readers
  (`persona_sharing.py:53`, `build_session.py:638`, `search/api.py:104`) — deferred cleanup release.
- Any change to document-level Vespa ACL (`get_acl_for_user`) — unchanged; managers affect entity-level access
  only.
- CE behavior — Group Manager is an EE capability (custom groups are EE); CE has only Basic + Admins.
