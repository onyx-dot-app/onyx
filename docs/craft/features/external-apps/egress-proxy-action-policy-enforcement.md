# Egress Proxy ↔ Action-Policy Enforcement

How the egress proxy reads the admin-configured action policies (shipped by the
built-in slice; see `action-policies.md`) and turns an arbitrary outbound request from a
Craft sandbox into a decision: **forward**, **hold for approval**, or **block**.

This plan defines the **read + match + resolve contract** between the proxy and
the policy system. The proxy's runtime/delivery model (in-process in
`api_server` vs. a separate sidecar) and the full approval UX/event flow are
deliberately left open — this plan keeps the contract independent of both.

## Issues to Address

- The policy data exists (catalog of actions with recognition rules; per-action
  admin choices in `external_app_policy`) but **nothing consumes it**. There is
  no enforcement and no code path from "outbound request" to "policy decision".
- For any outbound request a sandbox makes — via the Python helper, `curl`, or
  anything else — the proxy must be able to:
  1. **match the app** (which connected `external_app`, if any),
  2. **match the action** within that app (which catalog `EndpointSpec`),
  3. **resolve the governing policy** (`ALWAYS | ASK | DENY`),
  4. **act** (forward / hold-for-ASK / block).
- Resolution logic currently lives inline in an API-view function
  (`action_policy_views`). The proxy needs the *same* resolution. Two copies of
  a security decision will drift — they must share one implementation.
- An open posture decision must be made explicitly (below), not defaulted
  silently: today every unconfigured action resolves to `ASK` (fail-open for
  built-in off-catalog calls).

## Important Notes

- **Source-of-truth boundaries** (don't reinvent):
  - Catalog + recognition rules: `onyx/external_apps/providers/actions.py`
    (`EndpointSpec`, `MatchRule = RestRoute | GraphQLOp`). Per-provider catalogs
    in `providers/{slack,linear,google_calendar}.py`.
  - Stored admin choices: `external_app_policy` rows via
    `onyx/db/external_app.py::get_policies`.
  - App identity + URL patterns: `external_app.upstream_url_patterns`
    (the existing app-match layer — reuse it).
- **Two-level matching.** App match (regex on `upstream_url_patterns`) already
  exists in the egress path; this work adds the second level — action match
  within the app, using the catalog `MatchRule`s. `RestRoute` keys off HTTP
  method + path regex; `GraphQLOp` keys off the parsed request body's operation
  type + root field.
- **Provider-owned matching.** The action-match logic should live next to the
  catalog (in `onyx/external_apps`), exposing a generic function the proxy
  calls. Keep provider specifics out of the proxy; the proxy stays a thin
  policy *consumer*.
- **One resolution function.** Extract the current inline logic into a single
  `resolve_policy(app, action_id) -> EndpointPolicy` (and a request-level
  `decide(app, request) -> Decision`) that both `action_policy_views` and the
  proxy call. This is the linchpin — the admin preview and live enforcement must
  never disagree.
- **`MatchRule` is already serialisable.** Because the rules are a typed
  discriminated union, the proxy can consume them directly whether they come
  from code (built-in) or, later, from a stored row (custom apps re-add `match`
  as a serialised `MatchRule`). One matcher serves both.
- **OPEN DECISION — default posture.** `action-policies.md` specifies built-in
  off-catalog → `DENY` (fail closed). The current implementation resolves
  everything unconfigured to `ASK`. The proxy workstream must choose: (a) keep
  uniform `ASK`, or (b) reintroduce a per-app fail-closed default for built-in
  off-catalog requests. This is a security posture call — surface it to the
  owner; do not let it default by omission.
- **Transport-agnostic contract.** Define the decision API as a pure function
  over `(app, request descriptor) -> Decision { policy, matched_action? }`. If
  the proxy is in-process it's a direct call; if it's a sidecar it's the body of
  a thin RPC/HTTP endpoint. Don't couple the resolution logic to either.

## Implementation strategy

1. **Extract resolution into a shared home.** Move the stored-override-else-`ASK`
   logic out of `action_policy_views` into a single `resolve_policy` in the
   `onyx/external_apps` (or `onyx/db/external_app.py`) domain layer; have the
   API view call it. No behaviour change — this just creates the seam the proxy
   shares.
2. **Add an action matcher.** A provider-owned function that, given a connected
   `external_app` and a normalised request descriptor (method, path, optional
   parsed-body fields), tests the app's catalog `MatchRule`s and returns the
   matched `action_id` (or `None`). REST vs. GraphQL handled by the union.
3. **Compose the decision entry point.** `decide(app, request)`:
   app-match (existing) → action-match (step 2) → `resolve_policy` (step 1) →
   `Decision`. On no action match, apply the resolved default-posture
   (per the open decision above). Return enough metadata (matched action's
   `normalised_name`) for the approval prompt.
4. **Wire the proxy to call `decide`.** Behind the transport-agnostic contract.
   `ALWAYS` → forward; `DENY` → block (structured `403`); `ASK` → hand off to the
   approval flow (event emission / hold mechanism owned by the approval
   workstream — out of scope here).
5. **Resolve the doc overlap.** `../../../../plans/builtin-app-endpoint-policy-rules.md`
   already sketches a "proxy read contract" against the *old* schema
   (`default_for_unknown`, `external_app_endpoint_policy`, composite PK). Either
   supersede that section with this plan or update it to the current shape so
   there is one read contract.

## Tests

- **External-dependency unit** (preferred — exercises real catalog + DB, mocks
  nothing structural):
  - `resolve_policy`: stored override wins; unset resolves to the agreed default.
  - action matcher: a Slack REST path, a Google Calendar method+path, and a
    Linear GraphQL body each resolve to the expected `action_id`; an off-catalog
    request returns `None`.
  - `decide`: end-to-end app→action→policy for one `ALWAYS`, one `ASK`, one
    `DENY`, and one off-catalog request.
- **Integration** — only once a real enforcement entry point exists (proxy
  wired): assert an `ALWAYS` action forwards and a `DENY` action is blocked
  through the actual egress path. Defer until the runtime model is chosen.
- Don't add unit tests with heavy mocking for the matcher; the
  external-dependency tests cover it with the real catalog.
