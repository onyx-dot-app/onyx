# PAT Scopes — Permissions System

This is the "Permissions system" that the secrets-injection and search docs repeatedly defer to
(`secrets-injection/01-framework.md:162`, `02-onyx-pat.md:109`, `search/search-design.md:409,528`,
`search/4-craft-search-outstanding-questions.md:24`). Today a CRAFT PAT authenticates as the full
user at their own role; this plan adds per-token scopes so the sandbox can be handed a token that
can *search* but not drain chat history or touch the admin panel.

## Issues to Address

A Personal Access Token grants the full authority of the user it belongs to. `PersonalAccessToken`
(`backend/onyx/db/models.py:508`) has no scope column, and `fetch_user_for_pat`
(`backend/onyx/db/pat.py:27`) returns the real `User` verbatim and discards the matched token row.
The only attenuation is the optional expiry.

We want PATs to carry a scope — a subset of the user's authority that the token exposes — built on
the existing `Permission` enum (`backend/onyx/db/enums.py:469`) and the `require_permission`
dependency (`backend/onyx/auth/permissions.py:99`) rather than a parallel authorization system. The
first consumer is the Craft sandbox PAT minted by `ensure_sandbox_pat`
(`backend/onyx/server/features/build/db/sandbox.py:28`); the mechanism is general-purpose and
applies to user-created PATs too.

Five new token scopes, at a coarser, API-surface granularity than the existing capability
permissions:

- `READ_SEARCH` — search/query endpoints
- `READ_CHAT` — view chat sessions/messages
- `WRITE_CHAT` — create sessions, send messages
- `READ_ADMIN` — read-only admin panel (view settings, users, analytics; distinct from
  `FULL_ADMIN_PANEL_ACCESS`)
- `WILDCARD` (`*`) — passes all checks; the backward-compat default for existing PATs

## Important Notes

**The authority model is an intersection.** Effective authority for a request is
`expand(user.effective_permissions) ∩ expand(token.scopes)`. The user-side check is unchanged — a
token can never exceed its user. The token side is a new, second gate: `require_permission(P)`
passes iff `P ∈ expand(user_perms)` **and** `P ∈ expand(token_scopes)`.

**A closure already exists; we extend it.** `permissions.py` already implements implication: the
`IMPLIED_PERMISSIONS` adjacency map (`backend/onyx/auth/permissions.py:27`) and
`resolve_effective_permissions` (`:65`) compute the transitive closure of a granted set, with
`FULL_ADMIN_PANEL_ACCESS` short-circuiting to all permissions. `get_effective_permissions` (`:85`)
wraps it for a `User`. The new scopes plug into this same machinery rather than a second closure.

**The implication rules bridge two granularities.** The existing `Permission` values are capability
grants that live on `User.effective_permissions` (a `Mapped[list[str]]` JSONB column,
`backend/onyx/db/models.py:366`); the new scopes are API-surface verbs that live on a token. They
share one enum, so the intersection is a single vocabulary, but they occupy two domains —
`user.effective_permissions` should never literally contain `READ_SEARCH`, and a token's scopes are
normally the fine verbs or `WILDCARD`. Add these edges to `IMPLIED_PERMISSIONS`:

```
WILDCARD                → <all permissions>   (token-side sentinel; short-circuit)
BASIC_ACCESS            → READ_SEARCH, READ_CHAT, WRITE_CHAT
FULL_ADMIN_PANEL_ACCESS → READ_ADMIN
WRITE_CHAT              → READ_CHAT
```

`BASIC_ACCESS` currently implies nothing, so its row is new; `FULL_ADMIN_PANEL_ACCESS` already
short-circuits to everything, so `READ_ADMIN` falls out for free on the user side and the explicit
edge documents intent. `expand(S)` is the transitive closure applied at **check time** to both the
user permissions and the token scopes. Store the minimal granted set on each side; never persist an
expanded set, or a later rule change silently mismatches old rows. Closure over the 19-member enum
is free. `expand({})` (empty scope list) is `{}` — a token with no scopes passes nothing, which is
the correct fail-closed default.

Worked example — user is `BASIC_ACCESS`, token scope is `{READ_SEARCH}`:
`expand(user) = {BASIC_ACCESS, READ_SEARCH, READ_CHAT, WRITE_CHAT}`, `expand(token) = {READ_SEARCH}`.
A `require_permission(READ_SEARCH)` route passes; a `require_permission(WRITE_CHAT)` route blocks.

**Implication flows coarse→fine only, so route migration is mandatory.** A `READ_SEARCH` token does
*not* satisfy a `require_permission(BASIC_ACCESS)` route, because `BASIC_ACCESS ∉
expand({READ_SEARCH})`. A scoped token can only reach routes explicitly guarded with a permission in
its scope set. This is the safe direction — scoped tokens fail closed — but it means re-guarding
routes with the fine permissions is the work that makes scopes usable, not an optional follow-up.
WILDCARD tokens and backfilled legacy PATs are unaffected, since `expand({WILDCARD})` is everything.

**Unguarded routes are denied for scoped tokens (fail-closed, decided).** Most endpoints depend only
on `current_user`/`current_limited_user` with no `require_permission`. A scoped token is still a
valid active user, so without extra handling it would sail through every unguarded route — making
scoping advisory rather than a boundary. Given Craft's threat model (the secrets-injection effort
assumes the sandbox is hostile), that is too leaky. Therefore: when a request is authenticated via a
**non-WILDCARD** PAT, any matched route that did not declare a permission covered by the token's
`expand(scopes)` is denied. WILDCARD tokens and session/cookie auth bypass this gate entirely, so
existing behavior is preserved for everything except deliberately-scoped tokens. The gate is keyed
on auth type and scopes, not on `UserRole` — a PAT user keeps their real role, and `UserRole.LIMITED`
today applies only to anonymous users, so it is orthogonal to scoping.

**`WILDCARD` is a token-side sentinel only.** It is never a value in `User.effective_permissions`
and never a valid argument to `require_permission(...)` — it is the token-side analog of the
user-side `FULL_ADMIN_PANEL_ACCESS` override. Worth a guard (type-level or a startup assertion) so
nobody writes `require_permission(WILDCARD)`.

**`READ_ADMIN` is the heaviest migration.** Today read and write admin endpoints both sit behind
`FULL_ADMIN_PANEL_ACCESS`. Enforcing read-only admin means auditing those routes and splitting
read → `READ_ADMIN`, write → `FULL_ADMIN_PANEL_ACCESS`. A real audit, not a rename.

**Division of labor.** The token owner (separate work) handles the `PersonalAccessToken` scope
column + migration and the route re-guarding. This plan owns the enum/closure extension, the
auth-context plumbing contract, the second gate in `require_permission`, the fail-closed gate, and
the Craft-PAT scoping that is the acceptance test for the whole effort.

## Implementation strategy

1. **Extend the `Permission` enum** (`backend/onyx/db/enums.py:469`) with `READ_SEARCH`, `READ_CHAT`,
   `WRITE_CHAT`, `READ_ADMIN`, and the `WILDCARD` sentinel. Document in-place that some members are
   coarse capabilities (user-side) and some are fine API scopes (token-side), bridged by the closure.

2. **Extend the closure** in `backend/onyx/auth/permissions.py`: add the new edges to
   `IMPLIED_PERMISSIONS` (`:27`) and special-case `WILDCARD` in the resolver to short-circuit to the
   full set (mirroring the existing `FULL_ADMIN_PANEL_ACCESS` branch in `resolve_effective_permissions`,
   `:70`). Pure function, no I/O.

3. **Persist token scopes** (owner-handled). Add a `scopes` JSONB column to `PersonalAccessToken`
   (`backend/onyx/db/models.py:508`) holding `list[str]` of `Permission` values. Backfill existing
   rows to `["*"]` (WILDCARD) so legacy PATs are unchanged. This plan specifies the column shape and
   the WILDCARD-default contract.

4. **Plumb scopes into request context.** `fetch_user_for_pat` (`backend/onyx/db/pat.py:27`)
   currently returns only the `User` and drops the token row; it must also surface the matched
   token's `scopes`. The PAT branch of `optional_user` (`backend/onyx/auth/users.py:1809`) then
   stashes them on the request (e.g. `request.state.token_scopes`). Session/cookie auth, API-key
   auth, and legacy tokens default to `{WILDCARD}`. This is the seam the next two steps hang on.

5. **Second gate in `require_permission`** (`backend/onyx/auth/permissions.py:99`). After the
   existing user-permission check (which already raises
   `OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)` on failure, `:117`), also require
   `P ∈ expand(request.state.token_scopes)`, with WILDCARD short-circuiting. Same `OnyxError` on
   failure. This is the coarse→fine intersection.

6. **Fail-closed gate for unguarded routes.** For requests authenticated via a non-WILDCARD PAT,
   deny any matched route whose declared permissions are not covered by `expand(token_scopes)` —
   including routes that declared none. The route's `require_permission` declarations are already
   discoverable via the `_is_require_permission` sentinel that `check_router_auth`
   (`backend/onyx/server/auth_check.py:96`, wired in `backend/onyx/main.py:719`) uses to introspect
   route dependencies; reuse that detection. Implement as middleware or a router-level dependency.
   WILDCARD and non-PAT auth bypass. Denials raise `OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)`.

7. **Re-guard routes with fine permissions** (owner-handled): search → `READ_SEARCH`, chat-read →
   `READ_CHAT`, chat-write → `WRITE_CHAT`, read-only admin → `READ_ADMIN`. This plan provides the
   target mapping; the audit/migration is the token owner's.

8. **Scope the Craft PAT — the acceptance test.** Change `ensure_sandbox_pat`
   (`backend/onyx/server/features/build/db/sandbox.py:28`) to mint CRAFT PATs with
   `scopes=[READ_SEARCH]` (plus the minimal build/search scopes onyx-cli actually calls) instead of
   the implicit full-access WILDCARD. This retires the "CRAFT PAT grants full user access" caveat
   carried across the secrets-injection and search docs.

## Tests

Prefer external-dependency-unit and integration tests; the closure is the only piece that warrants a
pure unit test.

- **Unit — closure.** Pin the spec: `WILDCARD` expands to the full set; `BASIC_ACCESS` expands to
  include `READ_SEARCH/READ_CHAT/WRITE_CHAT`; `WRITE_CHAT` includes `READ_CHAT`;
  `FULL_ADMIN_PANEL_ACCESS` includes `READ_ADMIN`; `expand({})` is `{}`; transitivity holds. Add a
  completeness check that every `IMPLIED_PERMISSIONS` key and value is a real `Permission` member. Do
  not derive the expected output from the map — hardcode the spec.

- **External-dependency unit — auth context plumbing.** Mint a PAT with a real `scopes` value against
  a real DB, run it through the PAT auth path, and assert `request.state.token_scopes` carries the
  stored scopes; assert session auth and a WILDCARD-backfilled legacy PAT both resolve to
  `{WILDCARD}`.

- **Integration — intersection and fail-closed.** With real routes: a `READ_SEARCH` token reaches a
  `READ_SEARCH`-guarded search endpoint, is denied a `WRITE_CHAT`-guarded endpoint, and is denied an
  unguarded (`current_user`-only) endpoint. A `WILDCARD` token reaches all three. A `READ_ADMIN`
  token reaches a read-only admin endpoint but is denied a `FULL_ADMIN_PANEL_ACCESS` write endpoint.
  Confirm a token whose scope exceeds the user's permissions is still capped by the user (the
  intersection is min, not max). Assert denials return `OnyxErrorCode.INSUFFICIENT_PERMISSIONS`.

- **Integration — Craft PAT acceptance.** A live Craft session's PAT can call `company_search` /
  onyx-cli search but is denied chat-history reads and admin endpoints — the end-to-end proof the
  deferred caveat is closed.

## Out of scope

- Migrating `ApiKey` (the synthetic-service-account model, `backend/onyx/db/api_key.py`) onto the
  same scope mechanism. API keys already encode a restricted role via their synthetic user; folding
  them in is a later unification.
- A UI for users to choose scopes when minting a PAT. V1 scopes are set programmatically (Craft) or
  via API; the management UI is a follow-up.
- Per-resource / row-level scoping (e.g. "this token may read chat session X only"). Scopes are
  endpoint-surface grants, not object ACLs.
