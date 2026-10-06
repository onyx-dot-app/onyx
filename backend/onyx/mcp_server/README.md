# Onyx MCP Server

## Overview

The Onyx MCP server allows LLMs to connect to your Onyx instance and access its knowledge base and search capabilities through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

With the Onyx MCP Server, you can search your knowledgebase and
give your LLMs web search.

All access controls are managed within the main Onyx application.

### Authentication

Provide an Onyx Personal Access Token or API Key in the `Authorization` header as a Bearer token.
The MCP server quickly validates and passes through the token on every request.

A token scoped to `read:search` covers the document-search tool, including the listings of indexed
sources and document sets that a search may be filtered by. Add
`read:chat` or `write:chat` only if the client needs the chat surfaces. An unscoped token carries
the user's full access, so prefer a scoped one.

OAuth-capable MCP clients can connect through the public web URL when `OAUTH_PROVIDER_ENABLED=true`. The OAuth provider requires the shared Redis cache backend, so Lite deployments that use the Postgres cache do not support it yet. PAT and API-key authentication remain available.

### OAuth

Connect your OAuth-capable MCP client to `https://onyx.example.com/mcp/`. Onyx advertises the authorization server through the MCP authentication challenge. Sign in to Onyx, check the app and workspace, then approve access. The client handles token exchange and refresh.

Use HTTPS for `WEB_DOMAIN`. HTTP is allowed only for loopback development addresses. With an unsupported `WEB_DOMAIN`, the API server logs a warning and starts with OAuth off.

Apply the database migrations first. Cloud deployments need both the catalog and tenant migrations. Restart the API server, MCP server, primary worker, and Celery beat scheduler after deploying these changes.

Onyx supports public clients using authorization codes with S256 PKCE. Clients can register dynamically or use an HTTPS client metadata document. Client-secret and private-key authentication are not supported. Redirect URLs must match the registered URL exactly. HTTPS and loopback HTTP callbacks are accepted. Wildcards are not accepted.

Approval requires `read:search` and `create:user_api_keys` permissions. The granted scope is `read:search`. The app can search documents the user can access, use web search, and open web pages. Existing document permissions and workspace policy still apply. The token cannot create API keys, approve other apps, or call unrelated Onyx APIs.

Consent requires a signed-in standard user, not a service account, PAT, or API key. Cloud users must remain active members of the approving workspace.

Access tokens expire after 15 minutes. Refresh grants expire after 30 days, even when refreshed. Reusing a consumed refresh token revokes the whole grant. Normal refresh leaves earlier access tokens valid until they expire.

Use **Connected apps** in user settings to disconnect an app. Disconnect revokes all tokens for that grant. Signing out of Onyx does not disconnect apps.

The MCP resource URL is always `WEB_DOMAIN/mcp/`. Set the same `WEB_DOMAIN` and `OAUTH_PROVIDER_ENABLED` on the API server and MCP server.

The reverse proxy must expose these discovery URLs without requiring a session:

- `/.well-known/oauth-authorization-server/api/oauth-provider`
- `/.well-known/oauth-protected-resource/mcp/`

The provided nginx, Helm, and Next.js routes handle these paths. PostgreSQL stores hashed credentials and grants. Shared Redis stores short-lived consent requests and authorization codes. All API replicas must use the same databases and Redis. Deployments that set `CACHE_BACKEND=postgres` do not support MCP OAuth yet.

Each refresh deletes the grant's expired access tokens. The primary worker deletes expired grants, with their tokens, once a day. The default cloud multiplier makes it eight days. Catalog cleanup removes client registrations idle for 90 days. Lite deployments run both cleanups from the API server. Authentication enforces expiry immediately and does not wait for cleanup. Refresh history remains until the grant expires.

#### Troubleshooting

- A 503 means an authorization dependency or client metadata fetch is unavailable. Do not treat it as successful authentication. Some clients may ask you to connect again after a failed refresh.
- Check that the discovery document's resource URL matches the MCP endpoint. Set the same issuer and resource configuration on every API and MCP replica.
- Blocked private destinations and invalid client metadata are rejected as invalid clients. Network fetch failures return unavailable. Check that the metadata URL is public and reachable when troubleshooting a 503.
- In local development, `DEV_MODE=true` forces MCP backend calls to port 8080. To use `API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS` with a different local port, run the MCP process with `DEV_MODE=false`.

### Default Configuration
- **Transport**: HTTP POST (MCP over HTTP)
- **Port**: 8090 (shares domain with API server)
- **Framework**: FastMCP with FastAPI wrapper
- **Database**: None (all work delegates to the API server)

### Architecture

The MCP server is built on [FastMCP](https://github.com/jlowin/fastmcp) and runs alongside the main Onyx API server:

```
┌─────────────────┐
│  LLM Client     │
│  (Claude, etc)  │
└────────┬────────┘
         │ MCP over HTTP
         │ (POST with bearer)
         ▼
┌─────────────────┐
│  MCP Server     │
│  Port 8090      │
│  ├─ Auth        │
│  ├─ Tools       │
│  └─ Resources   │
└────────┬────────┘
         │ Internal HTTP
         │ (authenticated)
         ▼
┌─────────────────┐
│  API Server     │
│  Port 8080      │
│  ├─ Token auth  │
│  ├─ Search APIs │
│  └─ ACL checks  │
└─────────────────┘
```

## Configuring MCP Clients

### Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "onyx": {
      "url": "https://[YOUR_ONYX_DOMAIN]:8090/",
      "transport": "http",
      "headers": {
        "Authorization": "Bearer YOUR_ONYX_TOKEN_HERE"
      }
    }
  }
}
```

### Other MCP Clients

Most MCP clients support HTTP transport with custom headers. Refer to your client's documentation for configuration details.

## Capabilities

### Tools

The server provides three tools for searching and retrieving information:

1. `search_indexed_documents`
Search the user's private knowledge base indexed in Onyx. Returns ranked documents with content snippets, scores, and metadata.

Pass `agent` with an agent name to run the search as that Onyx agent. The search then applies the agent's knowledge scope (document sets, attached documents, start date) and its configured model. An unresolvable name returns an error listing the agents available to the user, so no lookup call is needed first.

`agent` and `document_set_names` are mutually exclusive. Explicit document sets replace an agent's knowledge scope rather than narrowing it, so passing both is rejected instead of silently returning out-of-scope results.

Filter values resolve on the search call, so clients do not need a lookup call first. `agent`, `source_types` and `document_set_names` are all validated: a value that does not resolve returns an error naming close matches, or the available values when there are few of them, rather than being dropped. A dropped filter would return a wider result set that looks correctly scoped, so these fail instead.

2. `search_web`
Search the public internet for current events and general knowledge. Returns web search results with titles, URLs, and snippets.

3. `open_urls`
Retrieve the complete text content from specific web URLs. Useful for fetching full page content after finding relevant URLs via `search_web`.

### Resources

1. `indexed_sources`
Lists all document sources currently indexed in the tenant (e.g., `"confluence"`, `"github"`). Use these values to filter results when calling `search_indexed_documents`.

2. `document_sets`
Lists the Document Sets accessible to the user. Use the returned `name` values with the `document_set_names` filter of `search_indexed_documents`.

3. `agents`
Lists the Onyx agents accessible to the user (`id`, `name`, `description`). Use a returned `name` with the `agent` filter of `search_indexed_documents`.

## Local Development

### Running the MCP Server

The MCP Server automatically launches with the `Run All Onyx Services` task from the default launch.json.

You can also independently launch the Server via the vscode debugger.

### Testing with MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is a debugging tool for MCP servers:

```bash
npx @modelcontextprotocol/inspector http://localhost:8090/
```

**Setup in Inspector:**

For PAT or API-key authentication:

1. Leave OAuth disabled in the client
2. Open the **Authentication** tab
3. Select **Bearer Token** authentication
4. Paste your Onyx bearer token
5. Click **Connect**

For OAuth, use the public frontend MCP URL, such as `http://localhost:3000/mcp/`. Start the frontend too, since it hosts the login and consent pages. Use the client's OAuth flow instead of pasting a bearer token.

Once connected, you can:
- Browse available tools
- Test tool calls with different parameters
- View request/response payloads
- Debug authentication issues

### Health Check

Verify the server is running:

```bash
curl http://localhost:8090/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "mcp_server"
}
```

### Environment Variables

**MCP Server Configuration:**
- `MCP_SERVER_ENABLED`: Enable MCP server (set to "true" to enable, default: disabled)
- `MCP_SERVER_PORT`: Port for MCP server (default: 8090)
- `MCP_SERVER_CORS_ORIGINS`: Comma-separated CORS origins (optional)
- `OAUTH_PROVIDER_ENABLED`: Let MCP clients connect with OAuth (set to "true" to enable, default: disabled). Requires Redis and an HTTPS `WEB_DOMAIN`, except on loopback hosts. Set identically on API and MCP servers.

**API Server Connection:**
- `API_SERVER_PROTOCOL`: Protocol for API server connection (default: "http")
- `API_SERVER_HOST`: Hostname for API server connection (default: "127.0.0.1")
- `API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS`: Optional override URL. If set, takes precedence over the protocol/host variables. Used for self-hosting the MCP server with Onyx Cloud as the backend.
