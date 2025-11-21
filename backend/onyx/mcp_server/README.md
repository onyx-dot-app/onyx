# Onyx MCP Server

## Overview

The Onyx MCP server allows LLMs to connect to your Onyx instance and access its knowledge base and search capabilities through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

With the Onyx MCP Server, you can search your knowledgebase,
give your LLMs web search, and upload and manage documents in Onyx.

All access controls are managed within the main Onyx application.

### Authentication

Provide an Onyx bearer token in the `Authorization` header. The MCP server forwards
the token to the main API server `/me` endpoint; the API validates the token and
applies the correct user and tenant context.

Depending on usage, the MCP Server may support OAuth in the future.

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
│  ├─ Auth (/me)  │
│  ├─ Tools       │
│  └─ DB Pool     │
└────────┬────────┘
         │ Internal HTTP
         │ (authenticated)
         ▼
┌─────────────────┐
│  API Server     │
│  Port 8080      │
│  ├─ Search API  │
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

1. `onyx_search_documents`
Search your Onyx knowledge base with semantic search. Supports filtering by source type, time range, and result limits. Returns ranked documents with content snippets, metadata, and match scores.

2. `onyx_web_search`
Search the public web via the `/web-search/search-lite` API using your configured provider (Exa or Serper+Firecrawl). Returns URL, title, snippet, and the provider type for each query. Requires `EXA_API_KEY` or `SERPER_API_KEY` + `FIRECRAWL_API_KEY` to be configured. Use `onyx_open_url` to fetch full content for specific URLs.

3. `onyx_open_url`
Fetch and extract full page content from web URLs via `/web-search/open-urls`. Useful for retrieving complete articles after finding them with `onyx_web_search`. Returns the content provider type along with each fetched page.

### Resources

1. `available_sources`
Returns a JSON payload enumerating every document source that currently has indexed content in the tenant. The `sources` array is a sorted list of the source enum values (e.g., `"confluence"`, `"github"`). Clients can use it directly to drive filter pickers before calling `onyx_search_documents`.

## Local Development

### Running the MCP Server

The MCP Server automatically launches with the `Run All Onyx Services` task.

You can also independently launch the Server via the vscode debugger.

### Testing with MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is a debugging tool for MCP servers:

```bash
npx @modelcontextprotocol/inspector http://localhost:8090/
```

**Setup in Inspector:**

1. Ignore the OAuth configuration menus
2. Open the **Authentication** tab
3. Select **Bearer Token** authentication
4. Paste your Onyx bearer token
5. Click **Connect**

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

- `MCP_SERVER_CORS_ORIGINS`: Comma-separated CORS origins (optional)
- `API_SERVER_BASE_URL` (or `ONYX_URL`): Full API base URL (e.g., `https://cloud.onyx.app/api`). If set, overrides protocol/host/port below.
- `API_SERVER_PROTOCOL`: Protocol for internal API calls (default: "http")
- `API_SERVER_HOST`: Host for internal API calls (default: "127.0.0.1")
- `API_SERVER_PORT`: Port for internal API calls (default: 8080)
