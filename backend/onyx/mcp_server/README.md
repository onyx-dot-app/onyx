# Onyx MCP Server

## Overview

The Onyx MCP server allows LLMs to connect to your Onyx instance and access its knowledge base and search capabilities through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

With the Onyx MCP Server, you can search your knowledgebase,
give your LLMs web search, and upload and manage documents in Onyx.

All access controls are managed within the main Onyx application.

### Authentication

Provide an Onyx Personal Access Token or API Key in the `Authorization` header as a Bearer token.
The MCP server quickly validates and passes through the token on every request.

The MCP server exposed by Onyx currently uses HTTP transport. The outbound
stdio connector support below is a separate MCP client capability.

## Admin-managed stdio connectors

This package documents the MCP server exposed *by* Onyx. Separately, Onyx can
act as an MCP client and launch a locally installed MCP server over stdio for
agent actions.

Stdio connectors are disabled by default because the configured executable
runs on the API host. A single-tenant operator can enable the admin-only
configuration surface with:

```bash
MCP_STDIO_ENABLED=true
```

After restarting the API and web services, an Onyx admin can choose **Local
process (stdio)** when adding an MCP server. The command and each argument are
passed directly to the MCP SDK without a shell. Environment values are stored
in the encrypted MCP connection config and are masked when read back.

The executable and all required packages must already exist in the API
server's runtime environment. Container deployments should install the MCP
server in a custom API image; Onyx does not download or install commands from
the admin form.

Stdio tools use the same public/user/group access rules and agent assignment
flow as HTTP MCP tools. They are not exposed to Craft sandboxes because the
API host's executable is not present inside those sandboxes.

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
- `API_SERVER_PROTOCOL`: Protocol for API server connection (default: "http")
- `API_SERVER_HOST`: Hostname for API server connection (default: "127.0.0.1")
- `API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS`: Optional override URL. If set, takes precedence over the protocol/host variables. Used for self-hosting the MCP server with Onyx Cloud as the backend.
