# Onyx agent plugin

The plugin makes Onyx the first source of context in every Claude Code or Codex session. It does three things:

- **Steers every prompt to Onyx.** A `UserPromptSubmit` hook adds a short directive to each question prompt: call `search_indexed_documents` before answering anything that may depend on company knowledge, and before any other search tool. No network call is involved, so the prompt is never delayed. Strict retrieval, below, is what keeps other tools from running first.
- **Connects the Onyx MCP server.** The `search_indexed_documents`, `search_web` and `open_urls` tools are loaded at session start, not deferred, and the server's own instructions say when to call them.
- **Optionally gates other retrieval tools.** With strict retrieval on, a `PreToolUse` hook denies other servers' search tools and web search until Onyx has been consulted for the current prompt.

An optional prefetch runs a raw Onyx search before each prompt and injects the top sections. It is off by default because it adds up to 3 seconds per prompt. See below.

The hook runs with `bun` or Node 23.6 or later, whichever the machine has. Without either, the hook exits 0 with a note on stderr and only the MCP server works.

## Install

The marketplace file in this directory points at a zip published as a GitHub release of this repository. Add it by URL and install the plugin:

```
/plugin marketplace add https://raw.githubusercontent.com/onyx-dot-app/onyx/main/extensions/agent-plugin/.claude-plugin/marketplace.json
/plugin install onyx@onyx
```

Claude Code then asks for:

| Option | Value |
| --- | --- |
| Onyx URL | Your Onyx web address without a trailing slash, for example `https://cloud.onyx.app` |
| Onyx API token | A personal access token with the `read:search` scope. Create one under Settings > Accounts & Access > Access Tokens in Onyx. |
| Strict retrieval | Off by default. Gates other search tools until Onyx has been consulted. See below. |
| Prefetch results | Off by default. Injects raw search results before each prompt. See below. |

Run `/plugin configure onyx@onyx` to change a value later.

To develop the plugin from a checkout, start Claude Code with `--plugin-dir extensions/agent-plugin` and set `ONYX_URL`, `ONYX_API_TOKEN` and optionally `ONYX_STRICT_RETRIEVAL=true` or `ONYX_PREFETCH=true` in the environment. The hooks read those variables. The configuration dialog does not run for a plugin loaded this way, and the MCP server reads only the configured options, so it does not connect in this mode.

Organizations can require the plugin on every machine through managed settings. See [Manage plugins for your organization](https://code.claude.com/docs/en/plugins/org).

## Codex

The same directory is a Codex plugin: `.codex-plugin/plugin.json` is the manifest Codex reads, `hooks/codex.json` holds the Codex hook definitions, and the repo marketplace at `.agents/plugins/marketplace.json` lists it. The manifest uses Codex's own format rather than the portable Agent Plugins one, because Codex loads bundled hooks only from its own format. Codex cannot take a per-user server URL from a plugin, so the plugin bundles no MCP server there. Add the Onyx server yourself, named `onyx`, then install the plugin:

```
codex mcp add onyx --url https://onyx.example.com/mcp/
codex mcp login onyx
codex plugin marketplace add onyx-dot-app/onyx --sparse extensions/agent-plugin --sparse .agents/plugins
codex plugin add onyx@onyx
```

Codex runs plugin hooks only after you trust them once in `/hooks`. Start a new session afterwards. Codex has no options dialog, so the hook reads `ONYX_STRICT_RETRIEVAL`, `ONYX_PREFETCH`, `ONYX_URL` and `ONYX_API_TOKEN` from the environment. The steering directive needs none of them. Codex's built-in web search is a hosted tool that hooks cannot gate, so strict retrieval covers other MCP servers only. The Stop nudge arrives as a continuation prompt in Codex, which is how its `Stop` hook continues a turn.

## How the prompt hook works

For each submitted prompt the hook injects one directive as additional context: Onyx holds the organization's knowledge base, so call `search_indexed_documents` before answering anything that may depend on company documents, people, decisions, processes, customers or internal systems, and before any other search tool or web search, and cite the url of each result. It skips slash commands, prompts shorter than 15 characters and prompts with no letters. Claude decides when the question needs Onyx, and the full search pipeline, with LLM selection and context expansion, runs only then.

## Strict retrieval

Strict retrieval is for teams that want Onyx consulted before any other knowledge source, every time. When it is on:

- Other MCP servers' tools whose names contain `search`, `query`, `retrieve`, `lookup`, `find` or `fetch`, and the built-in `WebSearch` tool, are denied until Onyx has been consulted for the current prompt.
- A call to `search_indexed_documents` counts as consulting Onyx. So does any HTTP response to a prefetch, even an error status, so a wrong URL or an old server never locks the gate. A prefetch that times out or cannot connect does not count.
- Prompts the hook skips, such as slash commands, do not gate anything.
- The denial reason tells Claude to call `search_indexed_documents` first.

Per-session state lives under the plugin data directory, or under `~/.cache/onyx-agent-plugin` when the plugin is loaded from a directory, and is pruned after a day.

## Prefetch

With prefetch on, the hook posts each question prompt to `POST /api/search/raw`, which runs retrieval with no LLM call, and injects the top five sections with title, source, url and an excerpt in place of the directive, under the 10,000 character limit Claude Code applies. The injected context names the cases where the full `search_indexed_documents` pipeline is still worth a tool call: the sections do not cover the question, the answer must combine several documents, or the user asks for the current state of something. When the raw search finds nothing, the hook tells Claude to run the full search before answering from any other source.

The request has a 3 second budget inside a 5 second hook timeout. A search that fails or times out injects the plain directive instead and never blocks the prompt. Each prompt is sent to your Onyx server, and results are filtered by your Onyx document permissions, the same as in the Onyx chat. The raw route needs an Onyx server that has it, and an older server returns 404, which the hook treats as a failed search.

With strict retrieval also on, a question turn that ends on the prefetch alone gets one `Stop` hook instruction: if the answer relies on company knowledge beyond what the prefetch returned, run the full search now and revise. The hook skips the continuation both hosts mark as stop-hook driven, so it nudges once per turn.

## Files

| Path | Purpose |
| --- | --- |
| `.claude-plugin/plugin.json` | Claude Code manifest and the options the user is asked for |
| `.codex-plugin/plugin.json` | Codex manifest, which declares no MCP server |
| `.claude-plugin/marketplace.json` | The hosted marketplace: the plugin version and its release zip URL |
| `.mcp.json` | The remote Onyx MCP server, loaded upfront |
| `hooks/hooks.json` | The prompt hook, the strict-retrieval gate and the stop nudge |
| `hooks/codex.json` | The hooks for Codex, with its events and tool names |
| `scripts/onyx-hook` | Runtime launcher for the hook |
| `scripts/hook.ts` | Hook implementation for both hosts |
| `scripts/hook.test.ts` | Hook tests for both hosts |
| `skills/onyx/SKILL.md` | Tells Claude when and how to use Onyx |

Typecheck with `bunx tsgo --noEmit -p extensions/agent-plugin/tsconfig.json`, run the hook tests with `bun test extensions/agent-plugin`, and validate with `claude plugin validate extensions/agent-plugin`.

## Release

The plugin version lives in the marketplace entry, not in `plugin.json`, so Claude Code can see a new version before it downloads the zip. To release:

1. Set `version` and the release URL in `.claude-plugin/marketplace.json`, and `version` in `.codex-plugin/plugin.json`, to the new version and merge that change.
2. Push the tag `agent-plugin/v<version>` on the merged commit.

The `release-agent-plugin` workflow checks the tag against both versions and the download URL, zips this directory, and uploads it to a GitHub release at the listed URL. Users who added the marketplace get the new version on their next `/plugin marketplace update onyx` or through auto-update.
