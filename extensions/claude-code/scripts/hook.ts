// Claude Code hook entry for the Onyx plugin: UserPromptSubmit steers Claude to
// Onyx, PreToolUse and PostToolUse run the strict gate, Stop nudges a full search.
import {
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

// The raw route makes no LLM call, so it is the only route fast enough for the prefetch budget.
const SEARCH_PATH = "/api/search/raw";
const SEARCH_TIMEOUT_MS = 3_000;
// /api/search/raw rejects longer queries.
const MAX_QUERY_CHARS = 2048;
// Shorter prompts are replies such as "yes" or "ok", not questions.
const MIN_PROMPT_CHARS = 15;
const MAX_RESULTS = 5;
const MAX_CONTENT_CHARS = 1500;
// Past 10,000 characters Claude Code swaps additionalContext for a file path.
const MAX_CONTEXT_CHARS = 9_500;
const STATE_TTL_MS = 24 * 60 * 60 * 1000;
const OWN_TOOL_PREFIX = "mcp__plugin_onyx_";
const RETRIEVAL_TOOL_PATTERN = /search|query|retriev|lookup|find|fetch/i;
const FULL_SEARCH_CALL = "search_indexed_documents on the Onyx MCP server";
// No network call, so it is the default and the fallback when a prefetch fails.
const STEER_CONTEXT =
  "Onyx holds this organization's knowledge base. For anything that may depend on " +
  "company documents, people, decisions, processes, customers or internal systems, " +
  `call ${FULL_SEARCH_CALL} before answering and before any other search tool or web search, ` +
  "and cite the url of each result you rely on. " +
  "Skip it for work that needs only the code and files in front of you.";
// Prefetched sections come from retrieval alone, so the header says when the
// full pipeline (LLM selection and context expansion) is worth a tool call.
const CONTEXT_HEADER =
  "Onyx knowledge base sections for this prompt, from raw retrieval only, ranked by relevance. " +
  "Use them before any other source and cite the url of each section you rely on. " +
  `Call ${FULL_SEARCH_CALL} before answering when the sections do not cover the question, ` +
  "when the answer must combine several documents, or when the user asks for the current state of something.";
const NO_RESULTS_CONTEXT =
  "Onyx raw retrieval found nothing for this prompt. " +
  `Call ${FULL_SEARCH_CALL} before answering from any other source.`;
const STOP_FEEDBACK =
  "This turn answered after Onyx raw retrieval only. If the answer relies on " +
  `company knowledge beyond what the prefetch returned, call ${FULL_SEARCH_CALL} now and revise. ` +
  "Otherwise finish.";

type HookInput = {
  session_id: string;
  hook_event_name: string;
  prompt?: string;
  tool_name?: string;
  stop_hook_active?: boolean;
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
  prefetch: boolean;
};

// consulted: the strict gate is open for this prompt. Set by a full search,
// any HTTP response to a prefetch, or a prompt with nothing to retrieve.
// awaitingFullSearch: a prefetch returned and the full tool has not run.
type SessionState = {
  consulted: boolean;
  awaitingFullSearch: boolean;
};

// results is null when Onyx gave no usable answer. consulted stays true on an
// HTTP error so a misconfigured token never locks the strict gate shut.
type SearchOutcome = {
  consulted: boolean;
  results: SearchResult[] | null;
};

// CLAUDE_PLUGIN_OPTION_* comes from /plugin configure. The bare name covers
// --plugin-dir development, where userConfig is never prompted.
function option(name: string): string | undefined {
  return process.env[`CLAUDE_PLUGIN_OPTION_${name}`] ?? process.env[name];
}

function flag(name: string): boolean {
  const value = option(name);
  return value === "true" || value === "1";
}

function readConfig(): PluginConfig | null {
  const url = option("ONYX_URL");
  const token = option("ONYX_API_TOKEN");
  if (!url || !token) {
    console.error(
      "onyx plugin: set the Onyx URL and API token with /plugin configure onyx@onyx",
    );
    return null;
  }
  return {
    url: url.replace(/\/+$/, ""),
    token,
    strict: flag("ONYX_STRICT_RETRIEVAL"),
    prefetch: flag("ONYX_PREFETCH"),
  };
}

// The fallback stays inside the user's home: a shared temp directory would let
// another local user plant symlinks under predictable session file names.
function stateDir(): string {
  const base =
    process.env.CLAUDE_PLUGIN_DATA ?? join(homedir(), ".cache", "onyx-claude-code");
  const dir = join(base, "sessions");
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  return dir;
}

function statePath(sessionId: string): string {
  const safeId = sessionId.replace(/[^A-Za-z0-9_-]/g, "_");
  return join(stateDir(), `${safeId}.json`);
}

// null means no usable state. The gate treats that as unknown and stays open,
// so broken storage never blocks the user.
function readState(sessionId: string): SessionState | null {
  try {
    return JSON.parse(readFileSync(statePath(sessionId), "utf8")) as SessionState;
  } catch {
    return null;
  }
}

// Write then rename so a concurrent reader never sees a partial file.
function writeState(sessionId: string, state: SessionState): void {
  const path = statePath(sessionId);
  const tmp = `${path}.${process.pid}.tmp`;
  writeFileSync(tmp, JSON.stringify(state));
  renameSync(tmp, path);
}

// Best effort: another session may prune the same file at the same time.
function pruneStaleState(): void {
  const dir = stateDir();
  const cutoff = Date.now() - STATE_TTL_MS;
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    try {
      if (statSync(path).mtimeMs < cutoff) {
        unlinkSync(path);
      }
    } catch {
      continue;
    }
  }
}

function emit(output: object): void {
  process.stdout.write(JSON.stringify(output));
}

function emitContext(event: string, additionalContext: string): void {
  emit({ hookSpecificOutput: { hookEventName: event, additionalContext } });
}

function errorName(err: unknown): string {
  return err instanceof Error ? err.name : "Error";
}

function isQuestionPrompt(prompt: string): boolean {
  return (
    !prompt.startsWith("/") &&
    prompt.length >= MIN_PROMPT_CHARS &&
    /\p{L}/u.test(prompt)
  );
}

async function search(
  config: PluginConfig,
  query: string,
): Promise<SearchOutcome> {
  try {
    const response = await fetch(`${config.url}${SEARCH_PATH}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.token}`,
        "Content-Type": "application/json",
      },
      // No neighboring chunks: the excerpt should show the matched section.
      body: JSON.stringify({ query, context_chunks: 0 }),
      signal: AbortSignal.timeout(SEARCH_TIMEOUT_MS),
      // A redirect would carry the prompt to another origin.
      redirect: "manual",
    });
    if (!response.ok) {
      console.error(`onyx plugin: search returned HTTP ${response.status}`);
      return { consulted: true, results: null };
    }
    const payload = (await response.json()) as SearchResponse;
    // A body without results is a server fault, not an empty search.
    return {
      consulted: true,
      results: Array.isArray(payload.results) ? payload.results : null,
    };
  } catch (err) {
    // Only the error name: a fetch error message can quote request headers.
    console.error(`onyx plugin: search request failed (${errorName(err)})`);
    return { consulted: false, results: null };
  }
}

function prefetchContext(results: SearchResult[] | null): string {
  if (!results) {
    return STEER_CONTEXT;
  }
  if (!results.length) {
    return NO_RESULTS_CONTEXT;
  }
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
      `${result.link ?? "no url"}\n` +
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
  if (!isQuestionPrompt(prompt)) {
    // Nothing to retrieve, so the strict gate has nothing to wait for.
    writeState(input.session_id, { consulted: true, awaitingFullSearch: false });
    return;
  }
  if (!config.prefetch) {
    writeState(input.session_id, { consulted: false, awaitingFullSearch: false });
    emitContext("UserPromptSubmit", STEER_CONTEXT);
    return;
  }
  const { consulted, results } = await search(
    config,
    prompt.slice(0, MAX_QUERY_CHARS),
  );
  writeState(input.session_id, {
    consulted,
    awaitingFullSearch: results !== null,
  });
  emitContext("UserPromptSubmit", prefetchContext(results));
}

function isOtherRetrievalTool(tool: string): boolean {
  if (tool.startsWith(OWN_TOOL_PREFIX)) {
    return false;
  }
  if (!tool.startsWith("mcp__")) {
    return true;
  }
  const toolName = tool.slice(tool.lastIndexOf("__") + 2);
  return RETRIEVAL_TOOL_PATTERN.test(toolName);
}

function preTool(input: HookInput, config: PluginConfig): void {
  const tool = input.tool_name ?? "";
  if (!config.strict || !isOtherRetrievalTool(tool)) {
    return;
  }
  const state = readState(input.session_id);
  if (!state || state.consulted) {
    return;
  }
  emit({
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason:
        `Onyx strict retrieval: call ${FULL_SEARCH_CALL} before ${tool}.`,
    },
  });
}

// One nudge per turn: Claude Code sets stop_hook_active on the continuation.
function stop(input: HookInput, config: PluginConfig): void {
  if (!config.strict || input.stop_hook_active) {
    return;
  }
  if (!readState(input.session_id)?.awaitingFullSearch) {
    return;
  }
  emitContext("Stop", STOP_FEEDBACK);
}

async function main(): Promise<void> {
  const input = JSON.parse(readFileSync(0, "utf8")) as HookInput;
  const config = readConfig();
  if (!config) {
    return;
  }
  switch (input.hook_event_name) {
    case "UserPromptSubmit":
      await userPrompt(input, config);
      break;
    case "PreToolUse":
      preTool(input, config);
      break;
    case "PostToolUse":
      writeState(input.session_id, { consulted: true, awaitingFullSearch: false });
      break;
    case "Stop":
      stop(input, config);
      break;
    default:
      console.error(`onyx plugin: unexpected hook event '${input.hook_event_name}'`);
  }
}

// A hook that exits non-zero is a non-blocking error, but keeping exit 0 means
// an unwritable state directory never surfaces as a hook failure to the user.
try {
  await main();
} catch (err) {
  console.error(`onyx plugin: hook failed (${errorName(err)})`);
}
