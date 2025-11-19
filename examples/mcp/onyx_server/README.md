# Onyx MCP Server

This example implements an [MCP](https://modelcontextprotocol.io/) server that exposes a
single tool for chatting with an Onyx deployment via the `/chat/send-message`
API. Every invocation creates a brand-new chat session automatically so the
only value supplied by the LLM is the user query. The tool returns the
concatenated answer text together with the top documents surfaced in the
response.

## Requirements

- Python 3.11+
- The `mcp` and `fastmcp` packages (already included in `backend/requirements/default.txt`)
- Network access to an Onyx deployment
- An Onyx API key with access to the chat APIs

## Configuration

The server reads its configuration from environment variables (command-line
flags take precedence):

- `ONYX_API_BASE_URL` – Base URL for the Onyx API. Defaults to
  `http://localhost:3000/api`.
- `ONYX_API_KEY` – Bearer token used for Onyx API authentication.
- `ONYX_DEFAULT_PERSONA_ID` – Persona that should be selected when a new chat
  session is created. Defaults to `0`.

## Running the server

```bash
cd examples/mcp/onyx_server
python3 server.py --host 127.0.0.1 --port 8000
```

You can also pass the base URL or API key explicitly:

```bash
python3 server.py --base-url http://localhost:3000/api --api-key "$ONYX_API_KEY"
```

The server listens using the HTTP MCP transport at `/mcp` by default. The
resulting endpoint can be referenced from Claude Code or any other MCP-capable
client.

## Tool reference

`onyx_chat(question: str)`

- Always creates a new chat session, ignoring any prior context.
- Streams the answer and returns:
  - `answer` – Concatenated answer text.
  - `top_documents` – Documents returned in the stream, if any.

The tool uses API key authentication for every Onyx API request. If the API key
is missing or invalid, the tool will raise an error message that surfaces to the
client.
