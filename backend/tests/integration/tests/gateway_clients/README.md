# Gateway Client Integration Tests

Exercises the Onyx AI gateway's Anthropic (`ee/onyx/server/gateway/anthropic_passthrough.py`)
and OpenAI (`ee/onyx/server/gateway/openai_passthrough.py`) passthrough endpoints with
REAL coding-agent CLIs: `@anthropic-ai/claude-code` and `@openai/codex`.

## Why this directory is different

Every other suite under `tests/integration` talks to an in-process FastAPI
`TestClient` (no real socket). Here the request is made by an external CLI
*subprocess*, which needs a real TCP listener. `conftest.py`'s
`_real_api_server` fixture therefore:

- Skips the whole module unless `GET {API_SERVER_URL}/health` returns the Onyx
  health payload (default `http://127.0.0.1:8080`) — you need a real,
  out-of-process dev `api_server` running, not just Postgres/Redis/etc.
- Swaps the shared `tests.integration.common_utils.http_client` client for a
  raw `httpx.Client` for the module's duration, so the existing Manager
  helpers (PAT, LLM provider) hit that real server too.
- Logs in as the standing dev admin (`admin_user@example.com`, see the repo
  `CLAUDE.md`) rather than creating a user or calling `reset_all()` — this
  suite must never wipe a shared, already-running deployment.

Skips vs failures: every missing prerequisite (server, npm, CLI install,
provider secrets) is a *skip* by default, so local boxes and unrelated lanes
stay usable. The CI lane for this directory sets
`GATEWAY_CLIENT_TESTS_REQUIRED=true` (and boots an in-container `api_server`
via `run_with_server.sh`), which turns all of those into hard failures so the
lane can never go green by silently skipping.

## Running locally

```bash
uv run --env-file .vscode/.env pytest backend/tests/integration/tests/gateway_clients
```

Requirements:
- A real `api_server` reachable at `API_SERVER_URL` (default `127.0.0.1:8080`;
  override with `API_SERVER_HOST` / `API_SERVER_PORT`, e.g. when 8080 already
  serves a different checkout). The server must run THIS branch's code, since
  the suite exercises both passthrough modules. An in-process TestClient is
  not enough: the CLI subprocesses need a real TCP socket.
- `node`/`npm` on `PATH` — each suite installs its pinned `claude` or `codex`
  CLI version into an independent throwaway npm prefix per module run.
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` resolvable via
  `tests/utils/aws_secrets.py` (env var, `.vscode/.env`, or AWS Secrets
  Manager). Tests declare these with `@pytest.mark.secrets(...)` and skip
  cleanly if a key is unavailable.
- The gateway's provider-side flags on: `ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED`
  and `OPENAI_GATEWAY_PASSTHROUGH_ENABLED` (both default on).

Models used: `claude-haiku-4-5` (Anthropic) and `gpt-5-mini` (OpenAI) — cheap
tiers per repo convention. Never `gpt-4o-mini`.

## Coverage

`test_claude_code_gateway.py`:
1. A basic `claude -p` turn answers correctly through `/gateway/v1/messages`.
2. A tool-use turn (`--allowedTools "Bash(ls:*)"`, `MAX_THINKING_TOKENS`)
   proves thinking-block signature replay across turns.
3. A direct `/v1/messages` call with the `web_search_20250305` server tool —
   a passthrough-only capability the OpenAI-shaped translation path cannot
   carry.
4. `count_tokens` exactness against a real turn's `usage.input_tokens`.
5. `mcp_servers` is refused with `400 INVALID_INPUT`.

`test_codex_gateway.py`:
1. A basic `codex exec --json` turn through `/gateway/v1/responses`.
2. Encrypted reasoning (`include=["reasoning.encrypted_content"]`) round-trips
   across two turns, proving the statelessness contract (`store` is always
   forced `false`).
3. `previous_response_id` is refused with `501 NOT_IMPLEMENTED`; an `mcp`
   tool entry is refused with `400 INVALID_INPUT`.

## Cost / runtime

Each test makes 1-3 cheap-tier LLM calls. Expect well under $0.01 total and
roughly 1-2 minutes of wall time (dominated by the client-specific `npm install`,
which is cached per module run, and CLI subprocess startup).
