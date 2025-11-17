# Onyx MCP Server

## Overview

The Onyx MCP server allows LLMs to connect to your Onyx instance and access its knowledge base and search capabilities through the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

With the Onyx MCP Server, you can search your knowledgebase,
give your LLMs web search, and upload and manage documents in Onyx.

All access controls are managed within the main Onyx application.

### Authentication

The Onyx MCP Server authenticates with Personal Access Tokens. 
You can generate one in the User Settings panel of Onyx.

Depending on usage, the MCP Server may support OAuth in the future.

### Default Configuration
- **Transport**: HTTP POST (MCP over HTTP)
- **Port**: 8090 (shares domain with API server)
- **Framework**: FastMCP with FastAPI wrapper
- **Database**: Shared connection pool with main API server (minimal size for PAT validation)

### Architecture

The MCP server is built on [FastMCP](https://github.com/jlowin/fastmcp) and runs alongside the main Onyx API server:

```
┌─────────────────┐
│  LLM Client     │
│  (Claude, etc)  │
└────────┬────────┘
         │ MCP over HTTP
         │ (POST with PAT)
         ▼
┌─────────────────┐
│  MCP Server     │
│  Port 8090      │
│  ├─ Auth (PAT)  │
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
        "Authorization": "Bearer YOUR_PAT_HERE"
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

#### 1. `onyx_search_documents`
Search your Onyx knowledge base with semantic search. Supports filtering by source type, time range, and result limits. Returns ranked documents with content snippets, metadata, and match scores.

#### 2. `onyx_web_search`
Search the public web using your configured provider (Exa or Serper+Firecrawl). Returns URL, title, and snippet for each result. Requires `EXA_API_KEY` or `SERPER_API_KEY` + `FIRECRAWL_API_KEY` to be configured.

#### 3. `onyx_open_url`
Fetch and extract full page content from web URLs. Useful for retrieving complete articles after finding them with `onyx_web_search`. Uses the same provider as web search.

### Resources

At this time, the MCP server does not expose any MCP Resources, Prompts, or Elicitations. Only Tools are available.

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
4. Paste your Personal Access Token
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

- `MCP_SERVER_NAME`: Server name (default: "onyx")
- `MCP_SERVER_VERSION`: Server version
- `MCP_SERVER_CORS_ORIGINS`: Comma-separated CORS origins (optional)
- `API_SERVER_PROTOCOL`: Protocol for internal API calls (default: "http")
- `API_SERVER_HOST`: Host for internal API calls (default: "127.0.0.1")
- `API_SERVER_PORT`: Port for internal API calls (default: 8080)
