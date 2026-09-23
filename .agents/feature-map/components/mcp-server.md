# MCP Server

> Onyx acting as an MCP **server**: an external LLM client (Claude Desktop, the
> MCP Inspector, any MCP-speaking agent) connects over HTTP and gets one search
> tool plus three read-only resources backed by Onyx's own retrieval pipeline.

**Domain:** platform
**Edition:** CE
**Owns:**
`backend/onyx/mcp_server_main.py`, `backend/onyx/mcp_server/api.py`, `auth.py`,
`utils.py`, `mcp.json.template`, `backend/onyx/mcp_server/tools/search.py`,
`backend/onyx/mcp_server/resources/agents.py`, `document_sets.py`,
`indexed_sources.py`, `backend/onyx/server/metrics/mcp_server.py`,
`mcp_common.py`, `deployment/helm/charts/onyx/templates/mcp-server-deployment.yaml`,
`mcp-server-service.yaml`, `ingress-mcp.yaml`, `mcp-server-servicemonitor.yaml`

**Read first:** `backend/onyx/mcp_server/README.md`. It is the design
rationale and the client-facing contract for this component; this document
maps it to code and adds verification guidance.

**Not this component:** `[[mcp-and-custom-tools]]` covers the opposite
direction: Onyx acting as an MCP **client**, connecting out to third-party MCP
servers an admin configures under Admin > Actions. That component's code lives
in `backend/onyx/server/features/mcp/` and `backend/onyx/tools/tool_implementations/mcp/`.
This document's code lives in `backend/onyx/mcp_server/` (no `s`, no `features/`
prefix). If you are unsure which one a change touches, check the direction of
the connection: who is dialing whom.

---

## 1. What the user experiences

A user who wants their LLM client (Claude Desktop, or any other MCP-capable
client) to search their company's Onyx knowledge base adds Onyx as an MCP
server in that client's configuration, pasting in a Personal Access Token or
API Key. From then on, the user can ask the client questions that require
looking things up in company data, and the client decides when to call the
search tool and reads back ranked, cited-content results, the same
retrieval quality as asking the same question in the Onyx chat UI.

The client can also list what sources are indexed, what Document Sets exist,
and what Onyx agents (personas) are available, so it can narrow a search
before running it.

---

## 2. Surfaces

### Process entry point

`backend/onyx/mcp_server_main.py:main` is a **separate process**, not a router
mounted on the main API server. It is a plain `uvicorn.run(mcp_app, ...)` call
against the FastAPI app built in `onyx/mcp_server/api.py:create_mcp_fastapi_app`.
It exits immediately, doing nothing, if `MCP_SERVER_ENABLED` is false
(`mcp_server_main.py:main`). Local development launches it two ways:
the "MCP Server" configuration in `.vscode/launch.json` (`uvicorn
onyx.mcp_server.api:mcp_app --reload --port 8090`), or directly via
`python -m onyx.mcp_server_main`.

### Tools

One callable tool, defined and registered via `@mcp_server.tool()` in
`backend/onyx/mcp_server/tools/search.py`:

| Tool | Function | What it does |
|---|---|---|
| `search_indexed_documents` | `search.py:search_indexed_documents` | Runs the full Onyx search pipeline against the company knowledge base. Filters by `source_types`, `document_set_names`, `time_cutoff`, or a named `agent`; `agent` and `document_set_names` are mutually exclusive (`search.py:_resolve_filters`). |

The README (`backend/onyx/mcp_server/README.md`) also documents `search_web`
and `open_urls`, and both are registered in the same file
(`search.py:search_web`, `search.py:open_urls`). They proxy to
`/web-search/search-lite` and `/web-search/open-urls` on the API server and do
not touch the internal document index or `SearchTool`. The task brief for this
document said "one tool"; the code and the README both show three. This
document covers all three, since they share one auth path and one process, but
`search_indexed_documents` is the one that reaches the shared retrieval
pipeline described in §4 and is the tool `[[access-control]]` and
`[[internal-search]]` care about.

### Resources

Three read-only MCP resources, registered via `@mcp_server.resource(...)` in
`backend/onyx/mcp_server/resources/`:

| Resource URI | Function | Returns | Why it exists |
|---|---|---|---|
| `resource://indexed_sources` | `indexed_sources.py:indexed_sources_resource` | Sorted list of connector source strings currently indexed for the tenant (`utils.py:get_indexed_sources`, backed by `GET /manage/indexed-sources`). | Lets a client discover valid values for the tool's `source_types` filter before calling it. |
| `resource://document_sets` | `document_sets.py:document_sets_resource` | List of `{name, description}` for Document Sets the user can access (`utils.py:get_accessible_document_sets`, backed by `GET /manage/document-set`, projected through `utils.py:DocumentSetEntry`). | Lets a client discover valid `document_set_names` values. |
| `resource://agents` | `agents.py:agents_resource` | List of `{id, name, description}` for personas the user can search with (`utils.py:get_accessible_agents`, backed by `GET /persona`, projected through `utils.py:AgentEntry`). | Lets a client discover valid `agent` names, which apply that agent's knowledge scope (document sets, attached documents, start date) and model. |

None of the three resources is strictly required before a search call: the
tool itself validates `source_types`, `document_set_names`, and `agent`
against the same backing calls and returns an error naming the available
values if a supplied value does not resolve (`search.py:_unknown_value_error`,
`_resolve_source_types`, `_validate_document_sets`, `_resolve_agent`). The
resources exist so a client can browse and filter proactively rather than
guess-and-fail.

### Env / config (`backend/onyx/configs/app_configs.py`)

| Variable | Default | Effect |
|---|---|---|
| `MCP_SERVER_ENABLED` | `false` | Gate. `mcp_server_main.py:main` exits without binding a port when unset. |
| `MCP_SERVER_HOST` | `0.0.0.0` | Bind address. |
| `MCP_SERVER_PORT` | `8090` | Listen port, shares the domain with the API server per the README. |
| `MCP_SERVER_CORS_ORIGINS` | unset | Comma-separated list; enables `CORSMiddleware` in `api.py:create_mcp_fastapi_app` when set. |
| `MCP_SERVER_API_REQUEST_TIMEOUT_SECONDS` | 300 | Timeout on the MCP server's outbound calls back to the API server (`search.py:_post_model`). |
| `API_SERVER_PROTOCOL`, `API_SERVER_HOST` | `http`, `127.0.0.1` | How the MCP process reaches the API server. |
| `API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS` | unset | Full override, used by the Helm deployment to point at the in-cluster API service, and documented for self-hosting the MCP server against Onyx Cloud as the backend. |

`MCP_SERVER_ALLOW_PRIVATE_NETWORK` and `MCP_SERVER_ALLOW_LOOPBACK`
(`app_configs.py`, near line 1236) look related by name but are not: they gate
the SSRF guard for outbound admin-configured MCP client connections, owned by
`[[mcp-and-custom-tools]]`, not this component.

### Deployment

Self-hosted docker-compose ships the `mcp_server` service **commented out** by
default in `deployment/docker_compose/docker-compose.prod.yml`,
`docker-compose.prod-no-letsencyrpt.yml`, and `docker-compose.template.yml`; an
operator uncomments it and sets `MCP_SERVER_ENABLED=true` to run it. Uncommented,
it runs `python -m onyx.mcp_server_main` in the same backend image, pointed at
`API_SERVER_HOST=api_server`.

The Helm chart deploys it unconditionally when `mcpServer.enabled` is set
(`deployment/helm/charts/onyx/templates/mcp-server-deployment.yaml`): its own
`Deployment` running `python onyx/mcp_server_main.py`, its own `Service`
(`mcp-server-service.yaml`), an `Ingress` at path `/mcp` on the API host
(`ingress-mcp.yaml`), and a `ServiceMonitor`
(`mcp-server-servicemonitor.yaml`) for its Prometheus metrics. It is wired to
the in-cluster API service via
`API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS`, not the protocol/host pair.
Liveness and readiness probes hit `/health`, the same unauthenticated
health-check route added in `api.py:create_mcp_fastapi_app`.

---

## 3. Data model

None. The README states it directly (`backend/onyx/mcp_server/README.md`:
"Database: None (all work delegates to the API server)"), and nothing in
`backend/onyx/mcp_server/` imports a DB session or SQLAlchemy model. Every
tool and resource call is an outbound HTTP request to the API server using the
caller's own bearer token (`search.py:_post_model`, `utils.py:get_http_client`).
The only local state is the shared `httpx.AsyncClient` (`utils.py:_http_client`),
torn down on shutdown (`utils.py:shutdown_http_client`, wired into
`api.py:create_mcp_fastapi_app`'s lifespan).

---

## 4. How it works

### 4.1 Connecting a client

A client (Claude Desktop, or the MCP Inspector) is configured with a URL and a
bearer token, shown in `backend/onyx/mcp_server/mcp.json.template`:

```json
{
  "mcpServers": {
    "Onyx": {
      "url": "https://cloud.onyx.app/mcp",
      "headers": {
        "Authorization": "Bearer [YOUR PAT OR API KEY HERE]"
      }
    }
  }
}
```

The README's Claude Desktop example is the same shape against a self-hosted
instance, pointing at `https://[YOUR_ONYX_DOMAIN]:8090/` directly rather than
through an `/mcp` ingress path.

### 4.2 Auth: every request, not just connection setup

`mcp_server = FastMCP(..., auth=OnyxTokenVerifier())` (`api.py`) wires
`OnyxTokenVerifier.verify_token` (`auth.py`) into FastMCP's per-request
authentication. On every MCP request, it makes a synchronous `GET /me` call to
the API server with `Authorization: Bearer {token}` (`auth.py:verify_token`).
A non-200 response returns `None`, which FastMCP treats as an authentication
failure; a 200 returns a minimal `AccessToken` with a fixed
`scopes=["mcp:use"]` (`auth.py`). **This `AccessToken.scopes` value is not the
real permission scope**, it is FastMCP's own token object; the real,
capability-bearing scopes (`read:search`, `read:chat`, `write:chat`, and the
rest of `db/enums.py:Permission`) live on the PAT or API key itself and are
resolved again, independently, when the token is later presented to the API
server (see §4.3). The MCP server never inspects or caches the token's real
scopes; it only checks that `/me` accepts the token at all, then forwards the
exact same token on every downstream call
(`search.py:_post_model`, `utils.py:get_indexed_sources`,
`get_accessible_document_sets`, `get_accessible_agents`).

Tokens are the PAT/API-key mechanism `[[auth-and-identity]]` owns
(`backend/onyx/auth/pat.py:generate_pat`, `hash_pat`). Scoping is
`db/enums.py:Permission.READ_SEARCH` / `READ_CHAT` / `WRITE_CHAT`, described in
that enum's own docstring as "API-surface scopes... coarser than the
capability tokens... exist primarily to scope Personal Access Tokens."

### 4.3 A search call, end to end

```
Claude Desktop -> POST /  (MCP tool call, bearer token)      mcp_server/api.py (port 8090)
  -> OnyxTokenVerifier.verify_token                          mcp_server/auth.py
       -> GET /me  (bearer token)                            API server, port 8080
  -> search_indexed_documents(...)                           mcp_server/tools/search.py
       -> _resolve_filters (agent / source_types / document_set_names)
       -> POST /search  (bearer token, SearchRequest)         API server, port 8080
            -> require_permission(Permission.READ_SEARCH)     onyx/server/features/search/api.py:search
            -> SearchTool(user=<resolved user>, emitter=NullEmitter(), bypass_acl=False, ...)
            -> search_tool.run(...)                            tools/tool_implementations/search/search_tool.py
```

The `/search` endpoint (`server/features/search/api.py:search`) is the same
endpoint `[[internal-search]]` documents as the programmatic entry point for
"onyx-cli, Craft sandbox, integrations." It resolves the caller from the
bearer token through the normal FastAPI-Users dependency chain
(`auth/users.py:current_user`), the same path a session cookie or any other
PAT/API-key caller goes through, then constructs a `SearchTool` with
`user=user` and **`bypass_acl=False`** hard-coded at the call site
(`search/api.py:search`, the `SearchTool(...)` construction). It passes
`emitter=NullEmitter()` because there is no chat stream to write packets to;
`chat/emitter.py:NullEmitter`'s own docstring names both the Search API and the
MCP server as its callers ("Used by callers that run tools outside the chat
streaming context (e.g. the Search API, MCP server)").

`search_tool.run(...)` is the same method the core chat loop's search tool
calls (`[[core-chat-loop]]` §4.1, `tools/tool_constructor.py`). The MCP path
and the chat path both terminate in `SearchTool.run`
(`tools/tool_implementations/search/search_tool.py:run`); `[[internal-search]]`
§4.1 walks its nine stages. What differs for MCP: no LLM answer is generated
afterward (the endpoint returns ranked `SearchResult` rows, not a chat
response), and the MCP tool always sets `emitter=NullEmitter()` since it is
never inside a chat turn.

`search_web` and `open_urls` (`search.py`) do not go through `SearchTool`; they
forward to `/web-search/search-lite` and `/web-search/open-urls` and return
whatever those endpoints give back.

---

## 5. Contracts and invariants

1. **The acting user's document ACLs apply.** The MCP server never searches
   the index itself; it delegates to `/search`, which builds `SearchTool` with
   `bypass_acl=False` (`search/api.py:search`). `[[access-control]]` §5.3
   states that no production code path currently sets `bypass_acl=True`
   (verified by `git log -S "bypass_acl=True" -- backend/onyx/onyxbot/`
   turning up no results, per that document); the only caller that could is
   the Slack bot's own flow, threaded through `process_message.py`, not
   anything MCP touches. **Verified: yes, MCP search is fully ACL-scoped to
   the acting user, by the same mechanism as chat search.** The integration
   test `backend/tests/integration/tests/mcp/test_mcp_server_search.py:test_mcp_search_respects_acl_filters`
   exercises this directly.
2. **A scoped token must not grant more than its scope.** The MCP server's own
   auth check (`auth.py:verify_token`) only confirms `/me` accepts the token;
   it does not enforce `read:search` itself. Enforcement happens downstream,
   at the API server, per endpoint: `/search` requires
   `Permission.READ_SEARCH` (`search/api.py:search`,
   `require_permission(Permission.READ_SEARCH)`); `/manage/indexed-sources`,
   `/manage/document-set`, and `/persona` (used by the three resources) carry
   their own permission requirements independently. `auth/permissions.py:require_permission`
   additionally caps by `request.state.token_scopes` when the authenticating
   token carries scopes narrower than the user's own permissions, so a
   `read:search`-only PAT cannot reach a `write:chat`-gated endpoint even
   though the MCP server itself never looked at the scope.
3. **An unscoped token carries the user's full access**, per the README. This
   follows from invariant 2: with no `token_scopes` set, `require_permission`
   only checks the user's own permissions, unconstrained by the token.
4. **The tool and resource names, argument schemas, and return shapes are a
   client-facing contract.** A configured Claude Desktop (or any other client)
   has this schema cached from its last successful list-tools call. Renaming
   `search_indexed_documents`, changing an argument name, or changing the
   `{"results": [...]}` / `{title, url, source_type, content, updated_at}`
   shape (`search.py:_to_mcp_dict`) breaks every already-configured client
   silently, with no migration path other than the client re-listing tools.
5. **`agent` and `document_set_names` are mutually exclusive** on
   `search_indexed_documents`, enforced in `search.py:_resolve_filters`.
   Explicit document sets replace an agent's knowledge scope rather than
   narrowing it, so honoring both would silently search outside the agent's
   intended scope.
6. **A filter value that does not resolve must fail, not silently drop.**
   `search.py:_unknown_value_error` and its callers raise `_FilterError`
   rather than proceeding with an unscoped search; a dropped filter would
   return a wider result set indistinguishable from a correctly scoped one.
7. **The MCP server must not become a way to bypass what the web path
   enforces.** It reuses the exact same `/search` endpoint and the same
   `Permission.READ_SEARCH` gate as any other programmatic caller
   (`[[onyx-api]]`); it adds no bypass of its own. See §9 for the one place
   this is not fully true today (rate limits).

---

## 6. Relationships

**Depends on**
- [[internal-search]]: owns the `SearchTool.run` pipeline this tool calls
  through `/search`.
- [[auth-and-identity]]: PATs and API keys are the only credential this
  server accepts; `auth.py:verify_token` delegates entirely to it.
- [[access-control]]: the ACL enforcement this server relies on and never
  duplicates.
- [[agents-personas]]: the `agent` filter and the `agents` resource surface
  personas and their knowledge scope.
- [[document-index]]: `indexed_sources` reflects what is actually indexed.
- [[rate-and-usage-limits]]: does not gate this surface today (see §9).
- [[onyx-api]]: the `/search`, `/manage/indexed-sources`,
  `/manage/document-set`, `/persona`, `/web-search/*`, and `/me` endpoints
  this server calls all live there.

**Depended on by**
- Nothing internal to Onyx. This is a leaf surface: external MCP clients are
  the only consumers.

**Named the opposite direction, do not confuse**
- [[mcp-and-custom-tools]]: Onyx as an MCP *client*. Different code, different
  process (it runs inside the main API server, not as its own entry point),
  different direction of connection.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| changes `search_indexed_documents`'s argument names, types, or return shape | every configured MCP client breaks silently; this is a versioned public contract, treat it like an API break |
| adds a tool or resource | update `backend/onyx/mcp_server/README.md`'s Capabilities section; add the tool/resource name to `MCPServerToolName` in `server/metrics/mcp_server.py` if it should be observable; consider whether it needs its own `Permission` scope |
| changes auth (`auth.py`, the `/me` delegation, or `Permission.READ_SEARCH`/`READ_CHAT`/`WRITE_CHAT`) | [[auth-and-identity]] for PAT/API-key issuance; re-run `backend/tests/integration/tests/mcp/test_mcp_server_auth.py`; re-verify invariant 2 in §5 |
| changes the retrieval pipeline (`SearchTool.run`, `_build_index_filters`, `_expand_queries_and_decide_scope`) | [[internal-search]] owns it; the change reaches this component automatically since `search_indexed_documents` calls the same `/search` endpoint chat's search tool ultimately reaches |
| changes `bypass_acl` plumbing anywhere in the chain | [[access-control]] §5.3 flags this as a security review regardless of which caller touches it; re-verify `search/api.py:search` still passes `bypass_acl=False` explicitly |
| changes `NullEmitter` | [[core-chat-loop]] also depends on it for the non-streaming save path; re-check both callers named in its docstring |
| adds a way for `search_indexed_documents` (or a future tool) to make an LLM call | re-read §9's rate-limit note; the call must stay behind the budget checks in `search/api.py:search` or add its own |
| changes `MCP_SERVER_ENABLED`/`MCP_SERVER_PORT`/`API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS` defaults | update the Helm chart's `mcp-server-deployment.yaml` env block and the commented docker-compose service to match |

---

## 8. How to verify a change

### Tests

```bash
# Unit tests: filter resolution, timeouts
cd backend && uv run pytest tests/unit/onyx/mcp_server

# Integration tests: real MCP session over streamable HTTP, real auth, real ACLs
cd backend && uv run pytest tests/integration/tests/mcp/test_mcp_server_auth.py
cd backend && uv run pytest tests/integration/tests/mcp/test_mcp_server_search.py
```

`test_mcp_server_search.py` is the one to read before touching anything in
§4-5: `test_mcp_document_search_flow`, `test_mcp_search_respects_acl_filters`,
`test_mcp_search_filters_by_document_set`, and `test_mcp_search_scopes_to_agent`
each open a real `mcp.ClientSession` over `streamablehttp_client` against a
running MCP server and call the tool/resources exactly as a real client would.

Tests under `backend/tests/external_dependency_unit/mcp/` and
`backend/tests/external_dependency_unit/server/features/mcp/` (OAuth dead
grants, admin API, access control on the admin-configured MCP surface) belong
to `[[mcp-and-custom-tools]]`, not this component.

### Manual reproduction

1. Set `MCP_SERVER_ENABLED=true` and start the server. Locally, either launch
   the "MCP Server" configuration in `.vscode/launch.json`, or run
   `uv run uvicorn onyx.mcp_server.api:mcp_app --port 8090` from `backend/`.
2. `curl http://localhost:8090/health` and confirm
   `{"status": "healthy", "service": "mcp_server"}`.
3. Mint a PAT scoped to `read:search` (see `[[auth-and-identity]]`) for a real
   user with indexed documents.
4. `npx @modelcontextprotocol/inspector http://localhost:8090/`, choose Bearer
   Token auth in the Authentication tab, paste the PAT, connect.
5. Call `search_indexed_documents` with a query you know matches indexed
   content; confirm results and that they only include documents that user can
   see. Try a query that should only surface a document the test user does
   *not* have access to and confirm it is absent.
6. Read the `indexed_sources`, `document_sets`, and `agents` resources and
   confirm they list only what the user can access.
7. Point Claude Desktop at the local server using the
   `mcp.json.template` shape and repeat a search from the client, to check the
   client-facing schema end to end.

---

## 9. Footguns

- **Client/server direction confusion.** "MCP" in this codebase means two
  opposite things depending on the directory: `backend/onyx/mcp_server/` is
  Onyx as a server (this document); `backend/onyx/server/features/mcp/` and
  `backend/onyx/tools/tool_implementations/mcp/` is Onyx as a client, admin
  configured, documented in `[[mcp-and-custom-tools]]`. Grepping "mcp" without
  checking the path will mix the two up.
- **It is a separate process, easy to forget when changing shared code.**
  A change to `SearchTool.run`, `Permission`, or `/search` is exercised by the
  main API server's own test suite, but this component's own process
  (`mcp_server_main.py`) is not started by most local dev flows unless
  `MCP_SERVER_ENABLED=true` is set. A regression here can go unnoticed unless
  `tests/integration/tests/mcp/` is run specifically.
- **`search_indexed_documents` spends LLM tokens, and `/search` meters it
  like chat.** `SearchTool.run` calls `select_sections_for_expansion`
  (`tools/tool_implementations/search/search_tool.py`) on every call, whatever
  the value of `skip_query_expansion`. When `skip_query_expansion=False` (the
  default), it also calls `keyword_query_expansion` and `decide_time_filter`
  (`search_tool.py:_expand_queries_and_decide_scope`). `search/api.py:search`
  runs `check_token_rate_limits` before it resolves an LLM,
  `check_api_key_usage` as a route dependency, and
  `check_llm_cost_limit_for_provider` (the cloud cost cap on Onyx-managed
  keys). Do not remove these on the grounds that MCP "never drives a chat
  turn"; see [[rate-and-usage-limits]] §9.
- **The MCP server's own token check is a liveness check, not a scope
  check.** `auth.py:verify_token` only confirms the token is accepted by
  `/me`; it does not know or enforce `read:search` vs `read:chat` vs
  `write:chat`. All real scope enforcement is downstream, per endpoint. A
  change that assumes the MCP layer itself gates by scope will be wrong.
- **Three tools exist, the task-defining brief for this document said one.**
  `search_web` and `open_urls` are real, registered tools
  (`mcp_server/tools/search.py`) alongside `search_indexed_documents`. They
  proxy to the web-search endpoints, not `SearchTool`, and carry no document
  ACL concerns of their own, but they are part of this server's contract and
  its blast radius (§7) all the same.
- **Local dev and Helm diverge on how the API server is addressed.**
  `.vscode/launch.json` and the commented docker-compose service use
  `API_SERVER_PROTOCOL`/`API_SERVER_HOST`; the Helm chart uses
  `API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS` exclusively
  (`mcp-server-deployment.yaml`). Both are read by the same helper,
  `variable_functionality.py:build_api_server_url_for_http_requests`, but a
  change to one config path without the other silently breaks only one
  deployment target.
