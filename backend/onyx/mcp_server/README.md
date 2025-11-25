# Onyx MCP Server

## Overview

The Onyx MCP server allows LLMs to connect to your Onyx instance and access its knowledge base and search capabilities through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

With the Onyx MCP Server, you can search your knowledgebase,
give your LLMs web search, and upload and manage documents in Onyx.

All access controls are managed within the main Onyx application.

### Authentication

Provide an Onyx Personal Access Token or API Key in the `Authorization` header as a Bearer token.
The MCP server quickly validates and passes through the token on every request.

Depending on usage, the MCP Server may support OAuth and stdio in the future.

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
│  ├─ /me (auth)  │
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

2. `search_web`
Search the public internet for current events and general knowledge. Returns web search results with titles, URLs, and snippets.

3. `open_urls`
Retrieve the complete text content from specific web URLs. Useful for fetching full page content after finding relevant URLs via `search_web`.

### Resources

1. `indexed_sources`
Lists all document sources currently indexed in the tenant (e.g., `"confluence"`, `"github"`). Use these values to filter results when calling `search_indexed_documents`.

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

**MCP Server Configuration:**
- `MCP_SERVER_ENABLED`: Enable MCP server (set to "true" to enable, default: disabled)
- `MCP_SERVER_PORT`: Port for MCP server (default: 8090)
- `MCP_SERVER_CORS_ORIGINS`: Comma-separated CORS origins (optional)

**API Server Connection:**
- `API_SERVER_BASE_URL`: Full API base URL (e.g., `https://cloud.onyx.app/api`). If set, overrides protocol/host/port below.
- `ONYX_URL`: Alternative to `API_SERVER_BASE_URL` (same purpose, either can be used)
- `API_SERVER_PROTOCOL`: Protocol for internal API calls (default: "http")
- `API_SERVER_HOST`: Host for internal API calls (default: "127.0.0.1")
- `API_SERVER_PORT`: Port for internal API calls (default: 8080)
