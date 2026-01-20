# AgentGateway Proxy

This proxy service bridges the gap between Onyx's LiteLLM-based LLM calls and AgentGateway's API.

## Why is this needed?

1. **URL Path Translation**: LiteLLM sends requests to `/chat/completions`, but AgentGateway expects requests at `/gemini`
2. **Streaming Response Conversion**: Onyx expects Server-Sent Events (SSE) streaming responses, but AgentGateway returns standard JSON responses

## Configuration

Add the following to your `.env` file:

```bash
# Enable the AgentGateway proxy
AGENTGATEWAY_ENABLED=true

# Your AgentGateway endpoint URL
AGENTGATEWAY_URL=http://your-agentgateway-host:8080/gemini
```

## Usage

1. Configure your `.env` file with the settings above
2. Start Onyx with `docker compose up --build`
3. In the Onyx admin UI, add a new LLM provider:
   - Select "AgentGateway" as the provider
   - The API Base URL will default to the proxy service
   - Select your preferred model (e.g., gemini-2.5-flash)

## How it works

```
Onyx → LiteLLM → Proxy (port 8888) → AgentGateway → Gemini
                    ↓
         - Translates /chat/completions → /gemini
         - Converts JSON response → SSE streaming
         - Normalizes usage token format
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENTGATEWAY_ENABLED` | Enable/disable the proxy | `false` |
| `AGENTGATEWAY_URL` | Your AgentGateway endpoint | (required) |
| `PROXY_PORT` | Port the proxy listens on | `8888` |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
