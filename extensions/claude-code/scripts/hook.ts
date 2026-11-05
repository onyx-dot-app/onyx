// Claude Code hook entry for the Onyx plugin: `user-prompt` injects Onyx results
// for every prompt, `pre-tool` and `post-tool` run the strict-retrieval gate.
import {
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const SEARCH_PATH = "/api/search";
const SEARCH_TIMEOUT_MS = 8_000;
// /api/search rejects longer queries.
const MAX_QUERY_CHARS = 2048;
// Shorter prompts are replies such as "yes" or "ok", not questions.
const MIN_PROMPT_CHARS = 15;
const MAX_RESULTS = 5;
const MAX_CONTENT_CHARS = 1500;
// Claude Code truncates additionalContext past 10,000 characters.
const MAX_CONTEXT_CHARS = 9_500;
const STATE_TTL_MS = 24 * 60 * 60 * 1000;
const OWN_TOOL_PREFIX = "mcp__plugin_onyx_";
const RETRIEVAL_TOOL_PATTERN = /search|query|retriev|lookup|find|fetch/i;
const CONTEXT_HEADER =
  "Onyx knowledge base results for this prompt, ranked by relevance. " +
  "Use them before any other source and cite the link of each result you rely on. " +
  "For follow-up questions call search_indexed_documents on the Onyx MCP server " +
  "before any other search tool.";

type HookInput = {
  session_id: string;
  hook_event_name: string;
  prompt?: string;
  tool_name?: string;
};

type SearchResult = {
  title: string;
  content: string;
  link: string | null;
  source_type: string;
  updated_at: string | null;
};

type SearchResponse = {
  results: SearchResult[];
};

type PluginConfig = {
  url: string;
  token: string;
  strict: boolean;
};

type SessionState = {
  consulted: boolean;
};

function readConfig(): PluginConfig | null {
  const env = process.env;
  // CLAUDE_PLUGIN_OPTION_* comes from /plugin configure. The plain names
  // cover --plugin-dir development, where userConfig is never prompted.
  const url = env.CLAUDE_PLUGIN_OPTION_ONYX_URL ?? env.ONYX_URL;
  const token = env.CLAUDE_PLUGIN_OPTION_ONYX_API_TOKEN ?? env.ONYX_API_TOKEN;
  if (!url || !token) {
    console.error(
      "onyx plugin: set the Onyx URL and API token with /plugin configure onyx",
    );
    return null;
  }
  const strict =
    env.CLAUDE_PLUGIN_OPTION_STRICT_RETRIEVAL ?? env.ONYX_STRICT_RETRIEVAL;
  return {
    url: url.replace(/\/+$/, ""),
    token,
    strict: strict === "true" || strict === "1",
  };
}

function stateDir(): string {
  const base =
    process.env.CLAUDE_PLUGIN_DATA ?? join(tmpdir(), "onyx-claude-code");
  const dir = join(base, "sessions");
  mkdirSync(dir, { recursive: true });
  return dir;
}

function statePath(sessionId: string): string {
  const safeId = sessionId.replace(/[^A-Za-z0-9_-]/g, "_");
  return join(stateDir(), `${safeId}.json`);
}

function readState(sessionId: string): SessionState {
  try {
    return JSON.parse(readFileSync(statePath(sessionId), "utf8")) as SessionState;
  } catch {
    return { consulted: false };
  }
}

function writeState(sessionId: string, state: SessionState): void {
  writeFileSync(statePath(sessionId), JSON.stringify(state));
}

function pruneStaleState(): void {
  const dir = stateDir();
  const cutoff = Date.now() - STATE_TTL_MS;
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).mtimeMs < cutoff) {
      unlinkSync(path);
    }
  }
}

function emit(output: object): void {
  process.stdout.write(JSON.stringify(output));
}

function shouldSearch(prompt: string): boolean {
  return (
    !prompt.startsWith("/") &&
    prompt.length >= MIN_PROMPT_CHARS &&
    /[a-z]/i.test(prompt)
  );
}

// null means Onyx did not answer. An empty list means it answered with nothing.
async function search(
  config: PluginConfig,
  query: string,
): Promise<SearchResult[] | null> {
  let response: Response;
  try {
    response = await fetch(`${config.url}${SEARCH_PATH}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.token}`,
        "Content-Type": "application/json",
      },
      // retrieval_only skips every LLM step so the hook answers in seconds.
      // Servers without it ignore the field and run the full pipeline.
      body: JSON.stringify({
        query,
        skip_query_expansion: true,
        retrieval_only: true,
      }),
      signal: AbortSignal.timeout(SEARCH_TIMEOUT_MS),
    });
  } catch (err) {
    console.error(`onyx plugin: search request failed: ${String(err)}`);
    return null;
  }
  if (!response.ok) {
    console.error(`onyx plugin: search returned HTTP ${response.status}`);
    return [];
  }
  const payload = (await response.json()) as SearchResponse;
  return payload.results;
}

function formatContext(results: SearchResult[]): string {
  const sections = [CONTEXT_HEADER];
  let used = CONTEXT_HEADER.length;
  for (const [index, result] of results.slice(0, MAX_RESULTS).entries()) {
    const meta = [
      result.source_type,
      result.updated_at ? `updated ${result.updated_at}` : null,
    ]
      .filter(Boolean)
      .join(", ");
    const section =
      `${index + 1}. ${result.title} (${meta})\n` +
      `${result.link ?? "no link"}\n` +
      result.content.slice(0, MAX_CONTENT_CHARS);
    if (used + section.length > MAX_CONTEXT_CHARS) {
      break;
    }
    sections.push(section);
    used += section.length;
  }
  return sections.join("\n\n");
}

async function userPrompt(input: HookInput, config: PluginConfig): Promise<void> {
  pruneStaleState();
  const prompt = (input.prompt ?? "").trim();
  if (!shouldSearch(prompt)) {
    // Nothing to retrieve, so the strict gate has nothing to wait for.
    writeState(input.session_id, { consulted: true });
    return;
  }
  const results = await search(config, prompt.slice(0, MAX_QUERY_CHARS));
  writeState(input.session_id, { consulted: results !== null });
  if (!results || results.length === 0) {
    return;
  }
  emit({
    hookSpecificOutput: {
      hookEventName: "UserPromptSubmit",
      additionalContext: formatContext(results),
    },
  });
}

function preTool(input: HookInput, config: PluginConfig): void {
  if (!config.strict) {
    return;
  }
  const tool = input.tool_name ?? "";
  if (tool.startsWith(OWN_TOOL_PREFIX)) {
    return;
  }
  if (tool.startsWith("mcp__") && !RETRIEVAL_TOOL_PATTERN.test(tool)) {
    return;
  }
  if (readState(input.session_id).consulted) {
    return;
  }
  emit({
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason:
        `Onyx strict retrieval: call search_indexed_documents on the Onyx MCP ` +
        `server before ${tool}.`,
    },
  });
}

function postTool(input: HookInput): void {
  writeState(input.session_id, { consulted: true });
}

async function main(): Promise<void> {
  const input = JSON.parse(readFileSync(0, "utf8")) as HookInput;
  const config = readConfig();
  if (!config) {
    return;
  }
  const event = process.argv[2];
  if (event === "user-prompt") {
    await userPrompt(input, config);
  } else if (event === "pre-tool") {
    preTool(input, config);
  } else if (event === "post-tool") {
    postTool(input);
  } else {
    console.error(`onyx plugin: unknown hook event '${event}'`);
  }
}

await main();
