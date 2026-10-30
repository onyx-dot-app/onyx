# MCP Server

> Onyx as an MCP server: an external MCP client such as Claude Code or Codex
> searches the company knowledge base with the user's own access. The server is
> a separate process with no database that forwards every call, with the
> caller's token, to the API server.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE

---

## User experience

- **A user adds Onyx to an MCP client.** The user gives the client the URL
  `https://<onyx domain>/mcp` and a Personal Access Token or API key as a
  bearer token. When the deployment has the Onyx OAuth provider (on only when
  `WEB_DOMAIN` is HTTPS, or HTTP on localhost), the client can instead sign the
  user in through the browser and get a token scoped to `read:search`. `backend/onyx/mcp_server/mcp.json.template` shows the client
  configuration.
- **The client's model** can then call `search_indexed_documents` for ranked
  results from the knowledge base, and `search_web` and `open_urls` for the
  web. It can read resources that list the indexed sources, the document sets
  and the agents that the user can use, so it can narrow a search before it
  runs one. Results contain only documents the user can see in Onyx.
- **When it fails**, a bad or expired token gets a 401. A PAT or API key
  gets a 401 for every rejection, including an API server outage. An OAuth
  token that the API server refuses for scope gets a 403 `insufficient_scope`
  challenge, an inactive subscription gets a 402, and an API server outage
  gets a 503. A tool call with an unknown source, document set or agent
  returns an error that names the valid values when the list is short. A deployment with no indexed sources, or with no vector database,
  returns an error from the search tool. With no active web search provider,
  `search_web` gets `INVALID_INPUT` from `/web-search/search-lite`, and the
  tool is still listed. `open_urls` falls back to the built-in crawler when no
  content provider is set.
- **An operator** gets the server by default in Docker Compose and Helm, and
  turns it off with `MCP_SERVER_ENABLED=false` (Compose) or
  `mcpServer.enabled: false` (Helm).

`backend/onyx/mcp_server/README.md` is the client-facing description of the
tools and resources.

---

## Scope

This component owns the MCP server process, its tools and resources, its token
verification, its metrics, the deployment routing that sends `/mcp` and the
protected-resource discovery path to it, the development proxy for `/mcp`, and
the MCP Compatibility workflow.

Its neighbours own:
- [[internal-search]]: `POST /search` and the `SearchTool` pipeline behind it.
- [[auth-and-identity]]: PATs, API keys and the Onyx OAuth provider that
  issues `onyx_oat_` tokens.
- [[authorization]]: how `require_permission` caps a scoped token by its scopes.
- [[web-search]]: the `/web-search/*` routes that `search_web` and `open_urls`
  call.
- [[rate-and-usage-limits]]: the budget checks on `/search`.
- [[mcp-and-custom-tools]]: the opposite direction, Onyx as an MCP client.
  Check who connects to whom before you change "MCP" code.

---

## Architecture

```
MCP client --bearer--> /mcp  (nginx or ingress)  --> mcp_server process (port 8090)
  OnyxTokenVerifier.verify_token
    PAT or API key   -> GET /me                     on the API server
    onyx_oat_ token  -> GET /oauth-provider/introspect
  search_indexed_documents
    _resolve_filters -> /manage/indexed-sources, /manage/document-set, /persona
    POST /search  (same bearer)  -> require_permission(READ_SEARCH)
                                 -> SearchTool(user=caller, emitter=NullEmitter())
```

**No state of its own.** Nothing in `backend/onyx/mcp_server/` opens a
database session. Each tool and resource call is an HTTP request to the API
server with the caller's bearer token, through one shared `httpx.AsyncClient`
(`mcp_server/utils.py:get_http_client`). The API server resolves the user,
applies permissions, ACLs and budgets, and does the work.

**Authentication.** `mcp_server/api.py` builds `FastMCP` with
`mcp_server/auth.py:build_mcp_server_auth`. When
`oauth_provider/config.py:OAUTH_PROVIDER_SETTINGS` is set, it wraps the
verifier in a `RemoteAuthProvider` that serves protected-resource metadata and
names the Onyx issuer. `OnyxTokenVerifier.verify_token` is async and runs on
every request. A PAT or API key goes to `/me`, and any failure returns no
token, which FastMCP reports as a 401. An `onyx_oat_` token goes to
`verify_oauth_token`, which raises `OnyxError` for a 402, a 403 or an outage.
`MCPAuthErrorMiddleware` turns that error into a JSON response, so these cases
are not reported as a bad token.

**Routing.** The advertised resource is `{WEB_DOMAIN}/mcp/`
(`oauth_provider/config.py`). Discovery advertises it without the trailing
slash, and `create_mcp_fastapi_app` adds a route alias for the
protected-resource metadata path with and without the slash, so clients can use
either URL form. Nginx (`deployment/data/nginx/mcp.conf.inc.template`) and the
Helm ingresses route `/mcp` and `/.well-known/oauth-protected-resource` to this
process. `/.well-known/oauth-authorization-server` goes to the API server
(`/oauth-provider/metadata`), not here.

---

## Contracts and traps

1. `pat-validated-not-scoped` **For a PAT or API key, the MCP auth check only
   validates the token.** `mcp_server/auth.py:OnyxTokenVerifier.verify_token`
   asks `/me` whether the token is accepted. The `scopes=["mcp:use"]` on the
   returned `AccessToken` is a FastMCP placeholder, not the token's real
   scope. Scope is enforced per endpoint on the API server: `/search` needs `READ_SEARCH`, and
   `backend/onyx/auth/permissions.py:require_permission` caps a scoped token by
   `request.state.token_scopes`, so an unscoped PAT or API key carries the
   user's full access. Do not assume the MCP layer gates a PAT by scope. Only
   `onyx_oat_` tokens are checked here, by
   `mcp_server/auth.py:OnyxTokenVerifier.verify_oauth_token`, for exactly
   `read:search` and the MCP resource.
2. `acl-from-search-route` **ACLs come from `/search`, not from this process.**
   `server/features/search/api.py:search` builds `SearchTool` with the resolved
   user, which always applies that user's ACL filters ([[access-control]]). A
   new tool must call an API route that applies ACLs. It must never query the
   index itself.
3. `oauth-token-route-allowlist` **An OAuth provider token reaches only an
   allowlist of routes.** `oauth_provider/auth.py:_ACCESS_ROUTES` admits
   `onyx_oat_` tokens only on the routes this server calls, and only with
   exactly `read:search`. A new API route that a tool calls must be added
   there. Otherwise the API server rejects OAuth clients on that route while
   PAT clients work. The allowlist is not enough: the token's scopes are set to
   `READ_SEARCH` only, so a route gated on any permission that `READ_SEARCH`
   does not imply returns 403 to every OAuth client
   (`auth/permissions.py:require_permission`). A malformed or refresh-type `onyx_oat_` bearer gets a 401
   (`oauth_provider/auth.py:oauth_provider_tenant_from_request`), and identity
   resolution never falls back to a browser cookie ([[auth-and-identity]]).
4. `client-facing-names-stable` **Tool and resource names, arguments and result
   shapes are a client contract.** Clients cache the tool list. A rename, a new
   required argument or a change to `mcp_server/tools/search.py:_to_mcp_dict`
   breaks configured clients with no error until they list tools again.
5. `errors-as-results` **Errors come back as a result, not as an MCP error.**
   `mcp_server/tools/search.py:_error_payload` returns `{"error": ...,
   "results": []}`. A client sees a successful call whose content is the error
   text.
6. `unknown-filter-fails` **An unknown filter value fails; it is never dropped.**
   `mcp_server/tools/search.py:_resolve_filters` raises `_FilterError` for an
   unknown source, document set or agent, because a dropped filter widens the
   search with no sign. `agent` and `document_set_names` are mutually exclusive: explicit document sets
   replace an agent's knowledge scope instead of narrowing it.
7. `search-is-metered` **Search spends LLM tokens and is metered.**
   `tools/tool_implementations/search/search_tool.py:SearchTool.run` makes LLM
   calls, and `/search` runs the token, API-call and cloud cost checks
   ([[rate-and-usage-limits]]). Keep a new LLM-calling tool behind the same checks.
8. `oauth-callback-not-this-server` **`/mcp/oauth/callback` is a web page, not
   this server.** It is the MCP client OAuth callback of
   [[mcp-and-custom-tools]]. Nginx has an exact `location` for it, and Helm has
   an exact path in
   `deployment/helm/charts/onyx/templates/ingress-mcp-oauth-callback.yaml`.
   Both win over the `/mcp` route. A routing change that sends it here breaks
   every member OAuth sign-in to an MCP server.
9. `api-server-url-per-target` **The process reaches the API server through
   `build_api_server_url_for_http_requests`**
   (`utils/variable_functionality.py:build_api_server_url_for_http_requests`).
   Compose sets `API_SERVER_HOST`. Helm sets
   `API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS` in
   `deployment/helm/charts/onyx/templates/mcp-server-deployment.yaml`. A change
   to one path can break only one deployment target.
10. `streamable-accept-header` **`_ensure_streamable_accept_header` rewrites the
    `Accept` header.** It sits in `mcp_server/api.py:create_mcp_fastapi_app`.
    FastMCP's streamable HTTP needs a request that accepts both JSON and event
    streams. The shim sets both when a client sends `*/*`,
    omits the header or leaves one out. Keep it.
11. `ssrf-env-false-lead` **`MCP_SERVER_ALLOW_PRIVATE_NETWORK` and
    `MCP_SERVER_ALLOW_LOOPBACK` are not settings of this server.** They seed
    the SSRF level for the MCP client in [[mcp-and-custom-tools]].

---

## Known issues

- A malformed `time_cutoff` is logged and ignored, so the search runs with no
  time bound. This breaks the "fail, do not widen" rule of
  [[#unknown-filter-fails]].
- A shared code change (`SearchTool`, `Permission`, `/search`) does not start
  this process in most local flows. Run the MCP integration tests to catch a
  regression here.
- The `/health` check in `mcp_server/api.py`, which the Helm probes call and
  which skips MCP auth, is an `@app.middleware("http")` function, which the
  API server forbids
  ([[streaming-protocol#pure-asgi-middleware]]). It is safe here because this
  app streams no chat. Do not copy it into the API server.

---

## Dependencies

- [[internal-search]]: the retrieval behind `search_indexed_documents`.
- [[auth-and-identity]]: token validation through `/me` and introspection,
  and the OAuth provider.
- [[authorization]]: token scopes and `require_permission`.
- [[access-control]]: the ACL filters that `/search` applies.
- [[agents-personas]]: the `agent` filter and the agents resource.
- [[web-search]]: the routes behind `search_web` and `open_urls`.
- [[rate-and-usage-limits]]: budgets on `/search`.
- [[onyx-api]]: the API routes this server calls.
- [[observability]]: Prometheus metrics in `server/metrics/mcp_server.py`.

---

## Recipes

- `mcp-server-tool` **A tool or resource.** Copy `search_web` in `mcp_server/tools/search.py`
  for a tool, or `mcp_server/resources/document_sets.py` for a resource; list
  the current set with `git grep -n '@mcp_server\.' backend/onyx/mcp_server`.
  Import a new module in the package `__init__.py`. Call an API route; do not
  query the database ([[#acl-from-search-route]]). Add the route to
  `_ACCESS_ROUTES` if OAuth clients may use it
  ([[#oauth-token-route-allowlist]]). Add a
  `server/metrics/mcp_server.py:MCPServerToolName` value for a tool, and update
  `backend/onyx/mcp_server/README.md`.
- `run-mcp-server-locally` **Run and probe the server locally.** Run `python -m onyx.mcp_server_main`
  with `MCP_SERVER_ENABLED=true`, check `/health`, and connect
  `npx @modelcontextprotocol/inspector` with a `read:search` PAT. A search must
  not return documents the user cannot see.
- `investigate-prod-oauth` **Investigate an OAuth sign-in that fails only in production.** Local OAuth
  discovery works only under `next dev`: `web/next.config.js` rewrites
  authorization-server discovery to `INTERNAL_URL` and protected-resource
  discovery to `MCP_INTERNAL_URL` in the `PHASE_DEVELOPMENT_SERVER` phase, and
  the `/mcp` proxy route serves only in development. A production build relies
  on nginx or the ingress, so a local pass does not prove production routing.
  Compare `deployment/data/nginx/mcp.conf.inc.template` and the Helm MCP
  ingresses, and check the advertised resource against `WEB_DOMAIN`.

---

## Verification

- Unit: `backend/tests/unit/onyx/mcp_server/`.
- Integration: `backend/tests/integration/tests/mcp/`. The MCP server tests
  open a real MCP session, and one checks [[#acl-from-search-route]].
- `.github/workflows/mcp-compatibility.yml` checks real nginx routing and real
  Claude Code and Codex OAuth sign-in on each PR and daily. A weekly job starts
  an isolated Compose stack and checks discovery and the auth challenge.
  Scheduled failures post a Slack alert. Its tests are in `deployment/tests/`.
