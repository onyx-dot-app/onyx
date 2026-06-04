# PAT Scopes

The "Permissions system" the secrets-injection and search docs defer to. A Personal Access Token
historically authenticates as its owner with the owner's full authority; this adds per-token scopes
so a token can be handed out that can *search* but not drain chat history or touch the admin panel.
The first consumer is the Craft sandbox PAT.

## Issues to Address

A PAT carries no scope — `fetch_user_for_pat` resolves the token to its `User` and the request runs
with the user's full permissions. The only attenuation is the optional expiry.

We want PATs to carry a scope: a subset of the owner's authority that the token exposes, built on the
existing `Permission` enum and `require_permission` dependency rather than a parallel authorization
system. Four token scopes, coarser than the existing capability permissions — they name request
surfaces, not admin capabilities:

- `READ_SEARCH` — search / query endpoints
- `READ_CHAT` — view chat sessions and messages
- `WRITE_CHAT` — create sessions, send messages
- `READ_ADMIN` — read-only admin panel, distinct from `FULL_ADMIN_PANEL_ACCESS`

A token with no scopes (`NULL`) is unrestricted — full user access. This is the backward-compatible
default for existing and unscoped tokens.

## How it works

**Authority is an intersection.** Effective authority for a request is
`expand(user permissions) ∩ expand(token scopes)`. The user-side check is unchanged — a token can
never exceed its owner. The token side is a second gate: `require_permission(P)` passes only if `P`
is in both expanded sets. An unrestricted PAT, session/cookie, and API-key auth carry no token
scopes (`None`), so there is no token-side restriction and their behavior is unchanged.

**One closure bridges two granularities.** `permissions.py` already computes the transitive closure
of a permission set under an implication map, with admin short-circuiting to everything. The new
scopes plug into that same map rather than a second system. The existing `Permission` values are
capability grants stored on the user; the new scopes are API-surface verbs stored on a token. They
share one enum — so the intersection is a single vocabulary — but occupy two domains: a user never
holds `READ_SEARCH` directly, it is implied. The implication edges:

```
BASIC_ACCESS            → READ_SEARCH, READ_CHAT, WRITE_CHAT
WRITE_CHAT              → READ_CHAT
FULL_ADMIN_PANEL_ACCESS → READ_ADMIN         (already covered by the admin short-circuit; explicit for intent)
```

The closure runs at check time on both sides; only the minimal granted set is persisted, so changing
a rule never leaves stale expanded data. "Unrestricted" is represented as the *absence* of scopes
(`NULL` in the column, `None` on the request) rather than a wildcard value — so it needs no entry in
the enum or the closure. An empty scope list (`[]`), by contrast, expands to nothing — a token with
an explicit empty scope set passes nothing, the correct fail-closed default.

Example — owner has `BASIC_ACCESS`, token scope is `READ_SEARCH`: a `READ_SEARCH` route passes; a
`WRITE_CHAT` route is denied even though the owner could otherwise write chat.

**Implication flows coarse→fine, so route guards must use the fine permissions.** A `READ_SEARCH`
token does not satisfy a route guarded by `BASIC_ACCESS` — a scoped token only reaches routes guarded
with a permission in its scope set. This is the safe direction (scoped tokens fail closed), but it
means re-guarding the relevant routes with the fine permissions is what makes scopes usable.
Unrestricted and legacy (`NULL`-scope) tokens are unaffected.

**Unguarded routes (fail-closed).** Most endpoints depend only on `current_user` with no
`require_permission`, so the intersection gate alone wouldn't constrain them — a scoped token would
pass. To close that, `optional_user` (the single HTTP auth funnel) denies a scoped PAT on any route
whose matched `request.scope["route"]` declares no `require_permission` dependency — reusing the same
`_is_require_permission` sentinel `check_router_auth` introspects. A scoped PAT therefore reaches only
routes guarded by a permission, and `require_permission` then adjudicates coverage. Unrestricted PATs,
sessions, and API-key auth (token scopes `None`) are untouched; websocket auth has its own path and is
unaffected.

**Identity endpoints are scope-exempt.** "Who am I" endpoints must be reachable by any valid token
regardless of authority — the industry-standard treatment of OAuth `/userinfo`. A route marks itself
with a `scope_exempt` dependency (a sibling `_is_scope_exempt` sentinel the gate honors alongside
`_is_require_permission`), and `/me` carries it. Without it the fail-closed gate would deny a scoped
PAT on `/me`, which a token has no business being locked out of.

**Anonymous-capable routes (chat).** The core chat endpoints (send-message, create-session,
view-session) admit anonymous users, so they are guarded with `require_permission(perm,
allow_anonymous=True)`, which resolves the anonymous user (when the tenant allows it) instead of
rejecting it, while still capping scoped PATs to `perm`. Anonymous, session, and unrestricted callers
are unaffected; a scoped token is held to `read:chat` / `write:chat`.

## Delivery

Sequenced so enforcement is complete before any scoped token exists:

1. **Permission vocabulary + closure** — the four API-surface scopes and their implication edges.
   *Shipped.*
2. **Token scopes + intersection** — a nullable `scopes` column (existing rows stay `NULL` =
   unrestricted), plumbed onto the request at PAT auth and intersected in `require_permission`.
   *Shipped.* Enforces on `require_permission` routes only.
3. **Fail-closed gate** — `optional_user` denies a scoped PAT on routes that declare no
   `require_permission`, so enforcement covers non-guarded routes too. *Shipped.*
4. **Re-guard routes** with the fine permissions (search / chat read+write / admin read vs. write).
   `POST /search` carries `READ_SEARCH` (the route the Craft sandbox's `onyx-cli search` hits).
   *Shipped.* On the chat surface, `read:chat` guards listing/viewing one's own sessions and
   chat-history search; `write:chat` guards create-session, send-message, and stop (it excludes delete
   and session-config). The remaining chat endpoints (delete, rename, share, config toggles, feedback,
   file download, token-count helpers) keep their existing guards and are not fine-scoped. *Shipped.*
   The web-search / `/manage` search surface and the `READ_ADMIN` admin split remain.
5. **Scope the Craft PAT** — `ensure_sandbox_pat` mints `[READ_SEARCH]` instead of unrestricted,
   retiring the "CRAFT PAT grants full user access" caveat. *Shipped.* This is the acceptance test for
   the effort: the search-scoped sandbox PAT reaches `POST /search` (via `onyx-cli search`) and `/me`,
   and nothing else.

Users select scopes when minting a token. `POST /user/pats` accepts a `scopes` list (omitted /
`null` = full access; an empty list is rejected), `GET /user/pats` returns each token's scopes, and
`GET /user/pats/scopes` lists the assignable scopes that back the settings-page selector. Search,
read-chat, and write-chat are assignable today; admin scopes follow once their routes are guarded.

## Tests

- **Unit (closure + gate).** Pin the implication spec with hardcoded expected sets plus a completeness
  check; cover the intersection truth table — an unrestricted token imposes no cap, scope-within-user
  passes, out-of-scope denied, a scoped token caps even an admin, and a token can't exceed its user.
- **External-dependency.** A scoped PAT's scopes round-trip through the real column; unscoped defaults
  to `NULL` (unrestricted).
- **Integration.** With real auth plumbing, a scoped PAT is denied on a route its scopes don't cover
  while an unrestricted PAT passes. Craft acceptance: a search-scoped session PAT can search but not
  read chat history or reach admin.

## Out of scope

- Folding `ApiKey` (the synthetic-service-account model) onto the same mechanism — API keys already
  encode a restricted role via their synthetic user.
- Per-resource / row-level scoping — scopes are endpoint-surface grants, not object ACLs.
