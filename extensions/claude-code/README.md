# Onyx plugin for Claude Code

The plugin makes Onyx the first source of context in every Claude Code session. It does three things:

- **Searches Onyx for every prompt.** A `UserPromptSubmit` hook sends the prompt to your Onyx search API and adds the top results to Claude's context before Claude starts to reason. No tool choice is involved, so other MCP servers and plugins cannot take precedence.
- **Connects the Onyx MCP server.** The `search_indexed_documents`, `search_web` and `open_urls` tools are loaded at session start, not deferred, for follow-up questions.
- **Optionally gates other retrieval tools.** With strict retrieval on, a `PreToolUse` hook denies other servers' search tools and web search until Onyx has been consulted for the current prompt.

The hook runs with `bun` or Node 23.6 or later, whichever the machine has. Without either, the hook exits 0 with a note on stderr and only the MCP server works.

## Install

The marketplace file in this directory points at a zip published as a GitHub release of this repository. Add it by URL and install the plugin:

```
/plugin marketplace add https://raw.githubusercontent.com/onyx-dot-app/onyx/main/extensions/claude-code/.claude-plugin/marketplace.json
/plugin install onyx@onyx
```

Claude Code then asks for:

| Option | Value |
| --- | --- |
| Onyx URL | Your Onyx web address without a trailing slash, for example `https://cloud.onyx.app` |
| Onyx API token | A personal access token with the `read:search` scope. Create one under Settings > Accounts & Access > Access Tokens in Onyx. |
| Strict retrieval | Off by default. See below. |

Run `/plugin configure onyx@onyx` to change a value later.

To develop the plugin from a checkout, start Claude Code with `--plugin-dir extensions/claude-code` and set `ONYX_URL`, `ONYX_API_TOKEN` and optionally `ONYX_STRICT_RETRIEVAL=true` in the environment. The hooks read those variables. The configuration dialog does not run for a plugin loaded this way, and the MCP server reads only the configured options, so it does not connect in this mode.

Organizations can require the plugin on every machine through managed settings. See [Manage plugins for your organization](https://code.claude.com/docs/en/plugins/org).

## How the prompt hook works

For each submitted prompt the hook posts the prompt text to `POST /api/search` with `retrieval_only` and `skip_query_expansion` set. It skips slash commands and prompts shorter than 15 characters. The top five results, with title, source, url and an excerpt, go to Claude as additional context under the 10,000 character limit Claude Code applies.

A search that fails or times out never blocks the prompt. The hook has a 10 second budget, and the request itself 8 seconds. On a server that supports `retrieval_only` the request makes no LLM calls and returns in seconds. A server without it runs the full search pipeline, which usually exceeds the budget, so the hook adds nothing there.

Each prompt is sent to your Onyx server. Results are filtered by your Onyx document permissions, the same as in the Onyx chat.

## Strict retrieval

Strict retrieval is for teams that want Onyx consulted before any other knowledge source, every time. When it is on:

- Other MCP servers' tools whose names contain `search`, `query`, `retrieve`, `lookup`, `find` or `fetch`, and the built-in `WebSearch` tool, are denied until Onyx has answered for the current prompt.
- The prompt hook's search counts as consulting Onyx. So does a call to `search_indexed_documents`.
- Prompts the hook skips, such as slash commands, do not gate anything.
- The denial reason tells Claude to call `search_indexed_documents` first.

Per-session state lives under the plugin data directory and is pruned after a day.

## Files

| Path | Purpose |
| --- | --- |
| `.claude-plugin/plugin.json` | Manifest and the options the user is asked for |
| `.claude-plugin/marketplace.json` | The hosted marketplace: the plugin version and its release zip URL |
| `.mcp.json` | The remote Onyx MCP server, loaded upfront |
| `hooks/hooks.json` | The prompt hook and the strict-retrieval gate |
| `scripts/onyx-hook` | Runtime launcher for the hook |
| `scripts/hook.ts` | Hook implementation |
| `skills/onyx/SKILL.md` | Tells Claude when and how to use Onyx |

Typecheck with `bunx tsgo --noEmit -p extensions/claude-code/tsconfig.json` and validate with `claude plugin validate extensions/claude-code`.

## Release

The plugin version lives in the marketplace entry, not in `plugin.json`, so Claude Code can see a new version before it downloads the zip. To release:

1. Set `version` and the release URL in `.claude-plugin/marketplace.json` to the new version and merge that change.
2. Push the tag `claude-code-plugin/v<version>` on the merged commit.

The `release-claude-code-plugin` workflow checks the tag against the marketplace entry, zips this directory, and uploads it to a GitHub release at the listed URL. Users who added the marketplace get the new version on their next `/plugin marketplace update onyx` or through auto-update.
