# Packet Processing & Path Sanitization Refactor Plan

Comprehensive refactor of the craft frontend packet processing pipeline.
Replaces `streamItemHelpers.ts` with a layered architecture that has a single parse
entry-point, strong types, and universal path sanitization.

---

## 1. Problem Statement

### 1.1 Two Consumers, Two Code Paths

The same raw backend packets are processed in two places with divergent logic:

| Consumer | When | How tool name is extracted |
|----------|------|--------------------------|
| `useBuildStreaming.ts` | Live SSE stream | `packet.tool_name \|\| packet.toolName \|\| packet.title` + passes **full packet object** to `normalizeKind` |
| `useBuildSessionStore.ts` (`convertMessagesToStreamItems`) | Loading from DB | `metadata.title` only + passes **string** to `normalizeKind` |

This causes **silent misclassification** when the backend changes `title` on
completion (e.g. task tool title becomes "Created 3 files" — the session store
path won't detect it as a task tool).

### 1.2 Path Leakage

Backend packets contain **absolute host paths** that leak sandbox infrastructure
details into the UI. Two deployment shapes exist, both always include the
sessions layer:

**Local dev** (always `sandboxes/{uuid}/sessions/{uuid}/...`):
```
/Users/wenxi-onyx/data/sandboxes/{sandbox-uuid}/sessions/{session-uuid}/outputs/web/page.tsx
/Users/wenxi-onyx/data/sandboxes/{sandbox-uuid}/sessions/{session-uuid}/files/linear/Engineering/ticket.json
```

**Kubernetes** (always `sessions/{uuid}/...`, no sandboxes prefix):
```
/workspace/sessions/{session-uuid}/outputs/web/page.tsx
/some/path/sessions/{session-uuid}/files/data.json
```

These paths appear in **5 distinct locations** within a single packet:

| Location | Example | Currently sanitized? |
|----------|---------|---------------------|
| `rawInput.filePath` | `/Users/.../sandboxes/uuid/sessions/uuid/outputs/web/page.tsx` | Yes (via `getFilePath` → `getRelativePath`) |
| `rawInput.command` | `cd /Users/.../sandboxes/uuid/sessions/uuid/outputs/web && python3 prepare.py` | **No** |
| `rawOutput.output` / `rawOutput.metadata.output` | `total 0\n/workspace/sessions/uuid/outputs/web/page.tsx\n...` | **No** |
| `title` (on completion) | `Users/wenxi-onyx/data/sandboxes/uuid/sessions/uuid/outputs/web/page.tsx` | Partially (only when used as file path fallback) |
| `content[].path` (diff items) | `/Users/.../sandboxes/uuid/sessions/uuid/outputs/web/page.tsx` | Yes (via `getFilePath`) |
| `locations[].path` | `/Users/.../sandboxes/uuid/sessions/uuid/outputs/web/AGENTS.md` | **No** |

### 1.3 Current `getRelativePath` Is Incomplete

The current function handles some patterns but misses others and has wrong
priority ordering:

```
Current patterns (in order):
1. /outputs/...           → too greedy, matches any /outputs/ anywhere
2. /data/sandboxes/[id]/sessions/[id]/... → correct
3. /sandboxes/[id]/sessions/[id]/...     → correct
4. /sandboxes/[id]/...                   → too broad (legacy, no longer needed)
5. fallback: filename only               → loses directory context
```

Problems:
- Pattern 1 matches `/home/user/my-outputs/project/outputs/file.txt` incorrectly
- Pattern 4 was for paths without sessions layer — no longer needed (local always
  has sessions layer now), but still catches sandboxes paths and over-strips them
- Pattern 5 loses all directory context (two different `Button.tsx` files become
  indistinguishable)
- None of these handle `/workspace/sessions/uuid/...` (kubernetes)
- The function is only applied to structured fields, not to freeform text
  (command strings, output text)

### 1.4 Other Issues

- `ToolCallKind` type lacks `"search"` and `"edit"` — both are sent by backend
  but silently mapped to `"other"`
- `extractFileContent` line-number regex `/^\d{5}\| /gm` fails for files with 100k+ lines
- `getTaskOutput` metadata stripping via `indexOf("<task_metadata>")` can
  truncate legitimate content
- `isTodoWriteTool` / `isTaskTool` have polymorphic signatures (`string | object`)
  that hide divergent behavior between the two consumers
- Trailing spaces in some `getToolTitle` return values ("Read ", "Writing ")
  create UI artifacts when no path follows

---

## 2. Path Sanitization Specification

### 2.1 The Single Rule

**Every path displayed in the UI must be relative to the session root.**

The "session root" is the directory containing `outputs/`, `files/`, etc.
The sanitization function must strip everything up to and including the session
anchor point, producing paths like:
- `outputs/web/page.tsx`
- `files/linear/Engineering/ticket.json`
- `agents.md`

### 2.2 `stripSessionPrefix`: The Universal Path Sanitizer

One regex, ordered by specificity (most specific first):

```typescript
/**
 * Strip sandbox/session path prefixes to produce a session-relative path.
 *
 * Both local and kubernetes ALWAYS include a sessions layer:
 *   Local:  /Users/.../sandboxes/{uuid}/sessions/{uuid}/outputs/web/page.tsx
 *   Kube:   /workspace/sessions/{uuid}/outputs/web/page.tsx
 *
 * Returns the path relative to the session root (the directory that
 * contains outputs/, files/, etc.)
 */
export function stripSessionPrefix(fullPath: string): string {
  if (!fullPath) return "";

  // 1. .../sandboxes/{uuid}/sessions/{uuid}/REST  →  REST
  //    Matches local dev (always sandboxes + sessions)
  const sbSession = fullPath.match(
    /\/sandboxes\/[0-9a-f-]+\/sessions\/[0-9a-f-]+\/(.+)$/
  );
  if (sbSession?.[1]) return sbSession[1];

  // 2. .../sessions/{uuid}/REST  →  REST
  //    Matches kubernetes (e.g. /workspace/sessions/...)
  const session = fullPath.match(/\/sessions\/[0-9a-f-]+\/(.+)$/);
  if (session?.[1]) return session[1];

  // 3. Fallback: keep last 3 path segments for context
  //    /some/unknown/deep/path/to/file.tsx  →  path/to/file.tsx
  const segments = fullPath.split("/").filter(Boolean);
  if (segments.length > 3) return segments.slice(-3).join("/");

  // 4. Already relative or short — return as-is
  return fullPath.startsWith("/") ? fullPath.slice(1) : fullPath;
}
```

Key improvements over current `getRelativePath`:
- UUID-anchored regex (`[0-9a-f-]+`) prevents false matches on directory names
  that happen to contain "sandboxes" or "sessions"
- No special-casing of `/outputs/` — it's just a subdirectory that naturally
  appears in the result after stripping the prefix
- Removed the legacy sandboxes-without-sessions pattern (no longer needed)
- Fallback preserves 3 segments instead of just the filename
- Handles the `/workspace/sessions/uuid/...` kubernetes pattern

### 2.3 `sanitizePathsInText`: Freeform Text Sanitizer

For command strings and output text where paths are embedded in freeform text:

```typescript
/**
 * Replace all absolute sandbox/session paths in freeform text with
 * session-relative paths.
 *
 * Handles paths embedded in commands, output listings, error messages, etc.
 * Matches both local and kubernetes path formats.
 */

// Pre-compiled regexes (module-level, not per-call)
// Order matters: most specific first to avoid partial matches
const SESSION_PATH_PATTERNS = [
  // Local: .../sandboxes/uuid/sessions/uuid/REST
  /(?:\/[\w._-]+)*\/sandboxes\/[0-9a-f-]+\/sessions\/[0-9a-f-]+\//g,
  // Kubernetes: .../sessions/uuid/REST  (no sandboxes prefix)
  /(?:\/[\w._-]+)*\/sessions\/[0-9a-f-]+\//g,
];

export function sanitizePathsInText(text: string): string {
  if (!text) return "";

  let result = text;
  for (const pattern of SESSION_PATH_PATTERNS) {
    // Reset lastIndex since we reuse the regex
    pattern.lastIndex = 0;
    result = result.replace(pattern, "");
  }
  return result;
}
```

Example transformations:
```
Input:  "cd /Users/wenxi-onyx/data/sandboxes/abc-123/sessions/def-456/outputs/web && python3 prepare.py"
Output: "cd outputs/web && python3 prepare.py"

Input:  "/workspace/sessions/def-456/outputs/web/page.tsx\n/workspace/sessions/def-456/outputs/web/globals.css"
Output: "outputs/web/page.tsx\noutputs/web/globals.css"

Input:  "chmod +x /Users/wenxi/data/sandboxes/abc/sessions/def/outputs/web/prepare.sh && /Users/wenxi/data/sandboxes/abc/sessions/def/outputs/web/prepare.sh"
Output: "chmod +x outputs/web/prepare.sh && outputs/web/prepare.sh"
```

### 2.4 Where Each Sanitizer Is Applied

| Packet field | Sanitizer | When applied |
|-------------|-----------|--------------|
| `rawInput.filePath` / `file_path` / `path` | `stripSessionPrefix` | During `parsePacket` (structured field) |
| `rawInput.command` | `sanitizePathsInText` | During `parsePacket` (freeform text) |
| `rawInput.description` | `sanitizePathsInText` | During `parsePacket` (may contain paths) |
| `rawOutput.output` | `sanitizePathsInText` | During `parsePacket` (freeform text) |
| `rawOutput.metadata.output` | `sanitizePathsInText` | During `parsePacket` (freeform text) |
| `content[].path` (diff items) | `stripSessionPrefix` | During `parsePacket` (structured field) |
| `content[].content.text` (file content) | **Not sanitized** (user's actual file content) | N/A |
| `title` (used as path fallback) | `stripSessionPrefix` | During `extractDiffPath` fallback |
| `locations[].path` | N/A | Not consumed by display layer (redundant with `rawInput.filePath`) |

**Important:** `content[].content.text` (the actual file body inside `<file>` tags)
is NOT sanitized — that's the user's real file content being displayed.

---

## 3. Architecture: Three Layers

### Layer 1: Types (`packetTypes.ts`)

All type definitions for raw and parsed packets.

```typescript
// ─── Raw Packet Field Access ─────────────────────────────────────────
// Centralizes all snake_case / camelCase field resolution.
// Every backend field name variant is listed ONCE here.

export function getRawInput(p: Record<string, unknown>): Record<string, unknown> | null {
  return (p.raw_input ?? p.rawInput ?? null) as Record<string, unknown> | null;
}

export function getRawOutput(p: Record<string, unknown>): Record<string, unknown> | null {
  return (p.raw_output ?? p.rawOutput ?? null) as Record<string, unknown> | null;
}

export function getToolCallId(p: Record<string, unknown>): string {
  return (p.tool_call_id ?? p.toolCallId ?? "") as string;
}

export function getToolNameRaw(p: Record<string, unknown>): string {
  return ((p.tool_name ?? p.toolName ?? p.title ?? "") as string).toLowerCase();
}

// ─── Parsed Packet Types (Discriminated Union) ──────────────────────

// Re-export from displayTypes — single source of truth
// (ToolCallKind in displayTypes.ts is updated to include "search" and "edit")
export type { ToolCallKind as ToolKind, ToolCallStatus as ToolStatus } from "../types/displayTypes";
import type { ToolCallKind as ToolKind, ToolCallStatus as ToolStatus } from "../types/displayTypes";
import type { TodoItem, TodoStatus } from "../types/displayTypes";

export type ToolName =
  | "glob" | "grep" | "read" | "write" | "edit" | "bash"
  | "task" | "todowrite" | "webfetch" | "websearch" | "unknown";

export interface ParsedTextChunk {
  type: "text_chunk";
  text: string;
}

export interface ParsedThinkingChunk {
  type: "thinking_chunk";
  text: string;
}

export interface ParsedToolCallStart {
  type: "tool_call_start";
  toolCallId: string;
  toolName: ToolName;
  kind: ToolKind;
  isTodo: boolean;
}

export interface ParsedToolCallProgress {
  type: "tool_call_progress";
  toolCallId: string;
  toolName: ToolName;
  kind: ToolKind;
  status: ToolStatus;
  isTodo: boolean;
  // Pre-extracted, pre-sanitized fields (ready for display)
  title: string;
  description: string;
  command: string;
  rawOutput: string;
  filePath: string;          // Session-relative
  subagentType: string | null;
  // Edit-specific
  isNewFile: boolean;
  oldContent: string;
  newContent: string;
  // Todo-specific
  todos: TodoItem[];
  // Task-specific
  taskOutput: string | null; // Extracted & cleaned output for completed tasks
}

export interface ParsedPromptResponse {
  type: "prompt_response";
}

export interface ParsedArtifact {
  type: "artifact_created";
  artifact: { id: string; type: string; name: string; path: string; preview_url: string | null };
}

export interface ParsedError {
  type: "error";
  message: string;
}

export interface ParsedUnknown {
  type: "unknown";
}

export type ParsedPacket =
  | ParsedTextChunk
  | ParsedThinkingChunk
  | ParsedToolCallStart
  | ParsedToolCallProgress
  | ParsedPromptResponse
  | ParsedArtifact
  | ParsedError
  | ParsedUnknown;
```

### Layer 2: Parser (`parsePacket.ts`)

Single function that converts a raw packet into a `ParsedPacket`.
All field resolution, tool detection, and **path sanitization** happen here.
Consumers never touch `Record<string, unknown>`.

```typescript
import { stripSessionPrefix, sanitizePathsInText } from "./pathSanitizer";
import {
  getRawInput, getRawOutput, getToolCallId, getToolNameRaw,
  type ParsedPacket, type ParsedToolCallStart, type ParsedToolCallProgress,
  type ParsedArtifact, type ToolName, type ToolKind, type ToolStatus,
} from "./packetTypes";
import type { TodoItem, TodoStatus } from "../types/displayTypes";

export function parsePacket(raw: unknown): ParsedPacket {
  if (!raw || typeof raw !== "object") return { type: "unknown" };
  const p = raw as Record<string, unknown>;
  const packetType = p.type as string | undefined;

  switch (packetType) {
    case "agent_message_chunk": // Live SSE
    case "agent_message":       // DB-stored format
      return { type: "text_chunk", text: extractText(p.content) };

    case "agent_thought_chunk": // Live SSE
    case "agent_thought":       // DB-stored format
      return { type: "thinking_chunk", text: extractText(p.content) };

    case "tool_call_start":
      return parseToolCallStart(p);

    case "tool_call_progress":
      return parseToolCallProgress(p);

    case "prompt_response":
      return { type: "prompt_response" };

    case "artifact_created":
      return parseArtifact(p);

    case "error":
      return { type: "error", message: (p.message ?? "") as string };

    default:
      return { type: "unknown" };
  }
}

// ─── Tool Name Resolution ─────────────────────────────────────────

function resolveToolName(p: Record<string, unknown>): ToolName {
  const rawName = getToolNameRaw(p);

  // Direct name match
  const NAME_MAP: Record<string, ToolName> = {
    glob: "glob", grep: "grep", read: "read", write: "write",
    edit: "edit", bash: "bash", task: "task",
    todowrite: "todowrite", todo_write: "todowrite",
    webfetch: "webfetch", websearch: "websearch",
  };
  if (NAME_MAP[rawName]) return NAME_MAP[rawName];

  // Fallback: detect by rawInput shape (handles title changes on completion)
  const ri = getRawInput(p);
  if (ri?.subagent_type || ri?.subagentType) return "task";
  if (ri?.todos && Array.isArray(ri.todos)) return "todowrite";

  return "unknown";
}

function resolveKind(toolName: ToolName, rawKind: string | null): ToolKind {
  // Tool name takes priority — it's the most reliable signal
  const TOOL_KIND_MAP: Record<ToolName, ToolKind> = {
    glob: "search", grep: "search",
    read: "read",
    write: "edit", edit: "edit",
    bash: "execute",
    task: "task",
    todowrite: "other",
    webfetch: "other", websearch: "search",
    unknown: "other",
  };
  const fromName = TOOL_KIND_MAP[toolName];
  if (fromName !== "other") return fromName;

  // Fall back to backend-provided kind
  if (rawKind === "search" || rawKind === "read" || rawKind === "execute"
      || rawKind === "edit" || rawKind === "task") {
    return rawKind;
  }
  return "other";
}

// ─── Shared Helpers ───────────────────────────────────────────────

/** Extract text from ACP content structure (string, {type,text}, or array) */
function extractText(content: unknown): string {
  if (!content) return "";
  if (typeof content === "string") return content;
  if (typeof content === "object" && content !== null) {
    const obj = content as Record<string, unknown>;
    if (obj.type === "text" && typeof obj.text === "string") return obj.text;
    if (Array.isArray(content)) {
      return content
        .filter((c) => c?.type === "text" && typeof c.text === "string")
        .map((c) => c.text)
        .join("");
    }
    if (typeof obj.text === "string") return obj.text;
  }
  return "";
}

function normalizeStatus(status: string | null | undefined): ToolStatus {
  if (status === "pending" || status === "in_progress" || status === "completed"
      || status === "failed" || status === "cancelled") {
    return status;
  }
  return "pending";
}

// ─── Edit / Diff Extraction ──────────────────────────────────────

/** Extract oldText and newText from content[].type==="diff" items */
function extractDiffData(content: unknown): {
  oldText: string; newText: string; isNewFile: boolean;
} {
  if (!Array.isArray(content)) return { oldText: "", newText: "", isNewFile: true };
  let oldText = "";
  let newText = "";
  for (const item of content) {
    if (item?.type === "diff") {
      if (typeof item.oldText === "string") oldText = item.oldText;
      if (typeof item.newText === "string") newText = item.newText;
    }
  }
  return { oldText, newText, isNewFile: oldText === "" };
}

/** Extract file path from content[].type==="diff" items (fallback when rawInput has no path) */
function extractDiffPath(p: Record<string, unknown>): string {
  const content = p.content as unknown[] | undefined;
  if (!Array.isArray(content)) return "";
  for (const item of content) {
    if (item && typeof item === "object" && (item as Record<string, unknown>).type === "diff") {
      const diffPath = (item as Record<string, unknown>).path as string | undefined;
      if (diffPath) return stripSessionPrefix(diffPath);
    }
  }
  // Final fallback: title field may contain a file path
  const title = p.title as string | undefined;
  if (title && title.includes("/")) return stripSessionPrefix(title);
  return "";
}

// ─── Description Builder ─────────────────────────────────────────

function buildDescription(
  toolName: ToolName, kind: ToolKind, filePath: string,
  ri: Record<string, unknown> | null, rawDescription: string
): string {
  // Task tool: use description from rawInput
  if (toolName === "task") {
    return rawDescription || "Running subagent";
  }
  // Read/edit: show file path
  if (kind === "read" || kind === "edit") {
    if (filePath) return filePath;
  }
  // Execute: use backend description
  if (kind === "execute") {
    return sanitizePathsInText(rawDescription) || "Running command";
  }
  // Search: show pattern
  if ((toolName === "glob" || toolName === "grep" || kind === "search")
      && ri?.pattern && typeof ri.pattern === "string") {
    return ri.pattern as string;
  }
  return buildTitle(toolName, kind, true);
}

// ─── Title Builder ───────────────────────────────────────────────

function buildTitle(toolName: ToolName, kind: ToolKind, isNewFile: boolean): string {
  // Edit/write: distinguish "Writing" (new file) vs "Editing" (existing)
  if (kind === "edit") return isNewFile ? "Writing" : "Editing";

  const TITLES: Record<ToolName, string> = {
    glob: "Searching files",
    grep: "Searching content",
    read: "Reading",
    write: "Writing",       // unreachable when kind === "edit", but safe fallback
    edit: "Editing",        // unreachable when kind === "edit", but safe fallback
    bash: "Running command",
    task: "Running task",
    todowrite: "Updating todos",
    webfetch: "Fetching web content",
    websearch: "Searching web",
    unknown: "Running tool",
  };
  return TITLES[toolName];
}

// ─── Raw Output Extraction ───────────────────────────────────────

/** Extract the appropriate output text based on tool kind.
 *  Returns raw unsanitized text — caller applies sanitizePathsInText. */
function extractRawOutputText(
  toolName: ToolName, kind: ToolKind,
  p: Record<string, unknown>, ro: Record<string, unknown> | null
): string {
  // Task tool: show the prompt (not the output JSON)
  if (toolName === "task") {
    const ri = getRawInput(p);
    if (ri?.prompt && typeof ri.prompt === "string") return ri.prompt as string;
    return "";
  }
  // Execute: prefer metadata.output, then output
  if (kind === "execute") {
    if (!ro) return "";
    const metadata = ro.metadata as Record<string, unknown> | null;
    return (metadata?.output || ro.output || "") as string;
  }
  // Read: extract file content from <file>...</file> wrapper
  if (kind === "read") {
    const fileContent = extractFileContent(p.content);
    if (fileContent) return fileContent;
    if (!ro) return "";
    if (typeof ro.content === "string") return ro.content;
    return JSON.stringify(ro, null, 2);
  }
  // Edit: show new text from diff
  if (kind === "edit") {
    const content = p.content as unknown[] | undefined;
    if (Array.isArray(content)) {
      for (const item of content) {
        if (item?.type === "diff" && typeof item.newText === "string") return item.newText;
      }
    }
    if (!ro) return "";
    return JSON.stringify(ro, null, 2);
  }
  // Search: files list or output string
  if (toolName === "glob" || toolName === "grep" || kind === "search") {
    if (!ro) return "";
    if (typeof ro.output === "string") return ro.output;
    if (ro.files && Array.isArray(ro.files)) return (ro.files as string[]).join("\n");
    return JSON.stringify(ro, null, 2);
  }
  // Fallback
  if (!ro) return "";
  return JSON.stringify(ro, null, 2);
}

/** Extract file content from content[].type==="content" items, stripping line numbers */
function extractFileContent(content: unknown): string {
  if (!Array.isArray(content)) return "";
  for (const item of content) {
    if (item?.type === "content" && item?.content?.type === "text") {
      const text = item.content.text as string;
      const fileMatch = text.match(/<file>\n?([\s\S]*?)\n?\(End of file[^)]*\)\n?<\/file>/);
      if (fileMatch?.[1]) {
        return fileMatch[1].replace(/^\d+\| /gm, ""); // Fixed: any line number width
      }
      return text;
    }
  }
  return "";
}

// ─── Todo Extraction ─────────────────────────────────────────────

function extractTodos(ri: Record<string, unknown> | null): TodoItem[] {
  if (!ri?.todos || !Array.isArray(ri.todos)) return [];
  return ri.todos.map((t: Record<string, unknown>) => ({
    content: (t.content as string) || "",
    status: normalizeTodoStatus(t.status),
    activeForm: (t.activeForm as string) || (t.content as string) || "",
  }));
}

function normalizeTodoStatus(status: unknown): TodoStatus {
  if (status === "pending" || status === "in_progress" || status === "completed") return status;
  return "pending";
}

// ─── Task Output Extraction ──────────────────────────────────────

function extractTaskOutput(ro: Record<string, unknown> | null): string | null {
  if (!ro?.output || typeof ro.output !== "string") return null;
  return ro.output
    .replace(/<task_metadata>[\s\S]*?<\/task_metadata>/g, "")
    .trim() || null;
}

// ─── Artifact Parsing ─────────────────────────────────────────────

function parseArtifact(p: Record<string, unknown>): ParsedArtifact {
  const artifact = p.artifact as Record<string, unknown> | undefined;
  return {
    type: "artifact_created",
    artifact: {
      id: (artifact?.id ?? "") as string,
      type: (artifact?.type ?? "") as string,
      name: (artifact?.name ?? "") as string,
      path: (artifact?.path ?? "") as string,
      preview_url: (artifact?.preview_url as string) || null,
    },
  };
}

// ─── Tool Call Parsing ────────────────────────────────────────────

function parseToolCallStart(p: Record<string, unknown>): ParsedToolCallStart {
  const toolName = resolveToolName(p);
  const rawKind = p.kind as string | null;
  return {
    type: "tool_call_start",
    toolCallId: getToolCallId(p),
    toolName,
    kind: resolveKind(toolName, rawKind),
    isTodo: toolName === "todowrite",
  };
}

function parseToolCallProgress(p: Record<string, unknown>): ParsedToolCallProgress {
  const toolName = resolveToolName(p);
  const rawKind = p.kind as string | null;
  const kind = resolveKind(toolName, rawKind);
  const ri = getRawInput(p);
  const ro = getRawOutput(p);
  const isTodo = toolName === "todowrite";

  // ── Edit-specific (extracted first — isNewFile needed by buildTitle) ──
  const diffData = kind === "edit"
    ? extractDiffData(p.content)
    : { oldText: "", newText: "", isNewFile: true };

  // ── File path (structured field → stripSessionPrefix) ──────────
  const rawFilePath = (ri?.file_path ?? ri?.filePath ?? ri?.path ?? "") as string;
  const filePath = rawFilePath ? stripSessionPrefix(rawFilePath) : extractDiffPath(p);

  // ── Command (freeform → sanitizePathsInText) ──────────────────
  const rawCommand = (ri?.command ?? "") as string;
  const command = sanitizePathsInText(rawCommand);

  // ── Description ───────────────────────────────────────────────
  const rawDescription = (ri?.description ?? "") as string;
  const description = buildDescription(toolName, kind, filePath, ri, rawDescription);

  // ── Output (freeform → sanitizePathsInText) ───────────────────
  const rawOutputText = extractRawOutputText(toolName, kind, p, ro);
  const rawOutput = sanitizePathsInText(rawOutputText);

  // ── Title ─────────────────────────────────────────────────────
  const title = buildTitle(toolName, kind, diffData.isNewFile);

  // ── Status ────────────────────────────────────────────────────
  const status = normalizeStatus(p.status as string | null);

  // ── Todo-specific ─────────────────────────────────────────────
  const todos = isTodo ? extractTodos(ri) : [];

  // ── Task-specific ─────────────────────────────────────────────
  const subagentType = (ri?.subagent_type ?? ri?.subagentType ?? null) as string | null;
  const taskOutput = (toolName === "task" && status === "completed")
    ? extractTaskOutput(ro)
    : null;

  return {
    type: "tool_call_progress",
    toolCallId: getToolCallId(p),
    toolName,
    kind,
    status,
    isTodo,
    title,
    description,
    command,
    rawOutput,
    filePath,
    subagentType,
    isNewFile: diffData.isNewFile,
    oldContent: diffData.oldText,
    newContent: diffData.newText,
    todos,
    taskOutput,
  };
}
```

### Layer 3: Path Sanitizer (`pathSanitizer.ts`)

Standalone module with `stripSessionPrefix` and `sanitizePathsInText` as
specified in section 2.

This is a separate file because:
- It has zero dependencies (pure string functions)
- It can be unit-tested exhaustively with a truth table
- It may be needed outside the packet pipeline (e.g., file browser, artifact display)

---

## 4. Consumer Integration

### 4.1 `useBuildStreaming.ts` (Live SSE)

```typescript
import { parsePacket } from "@/app/build/utils/parsePacket";

await processSSEStream(response, (rawPacket) => {
  const packet = parsePacket(rawPacket);

  switch (packet.type) {
    case "text_chunk":
      handleTextChunk(sessionId, packet.text);
      break;

    case "thinking_chunk":
      handleThinkingChunk(sessionId, packet.text);
      break;

    case "tool_call_start":
      if (packet.isTodo) {
        // Skip — todo pill created on first progress with actual items
        lastItemType = "tool";
        break;
      }
      appendStreamItem(sessionId, {
        type: "tool_call",
        id: packet.toolCallId,
        toolCall: {
          id: packet.toolCallId,
          kind: packet.kind,
          title: "",    // Populated on progress
          status: "pending",
          description: "",
          command: "",
          rawOutput: "",
          subagentType: undefined,
          isNewFile: true,
          oldContent: "",
          newContent: "",
        },
      });
      lastItemType = "tool";
      break;

    case "tool_call_progress":
      if (packet.isTodo) {
        upsertTodoListStreamItem(sessionId, packet.toolCallId, {
          id: packet.toolCallId,
          todos: packet.todos,
          isOpen: true,
        });
        break;
      }

      updateToolCallStreamItem(sessionId, packet.toolCallId, {
        status: packet.status,
        title: packet.title,
        description: packet.description,
        command: packet.command,
        rawOutput: packet.rawOutput,
        subagentType: packet.subagentType ?? undefined,
        ...(packet.kind === "edit" && {
          isNewFile: packet.isNewFile,
          oldContent: packet.oldContent,
          newContent: packet.newContent,
        }),
      });

      // Output file detection (uses pre-sanitized filePath)
      runOutputFileDetectors(sessionId, packet.filePath, packet.kind);

      // Task completion → emit text StreamItem
      if (packet.taskOutput) {
        appendStreamItem(sessionId, {
          type: "text",
          id: genId("task-output"),
          content: packet.taskOutput,
          isStreaming: false,
        });
        lastItemType = "text";
        accumulatedText = "";
      }
      break;

    case "prompt_response":
      finalizeAndSaveMessage(sessionId);
      break;

    case "error":
      updateSessionData(sessionId, { status: "failed", error: packet.message });
      break;
  }
});
```

### 4.2 `useBuildSessionStore.ts` (Loading from DB)

```typescript
import { parsePacket } from "@/app/build/utils/parsePacket";

function convertMessagesToStreamItems(messages: BuildMessage[]): StreamItem[] {
  const items: StreamItem[] = [];

  for (const message of messages) {
    if (message.type === "user") continue;
    const metadata = message.message_metadata;
    if (!metadata || typeof metadata !== "object") continue;

    // SAME parsePacket — identical classification for both code paths
    const packet = parsePacket(metadata);

    switch (packet.type) {
      case "text_chunk":
        if (packet.text) {
          items.push({ type: "text", id: message.id || genId("text"), content: packet.text, isStreaming: false });
        }
        break;

      case "thinking_chunk":
        if (packet.text) {
          items.push({ type: "thinking", id: message.id || genId("thinking"), content: packet.text, isStreaming: false });
        }
        break;

      case "tool_call_progress":
        if (packet.isTodo) {
          // Upsert: update existing todo_list or create new one
          const existingIdx = items.findIndex(
            (item) => item.type === "todo_list" && item.todoList.id === packet.toolCallId
          );
          if (existingIdx >= 0) {
            const existing = items[existingIdx];
            if (existing.type === "todo_list") {
              items[existingIdx] = {
                ...existing,
                todoList: { ...existing.todoList, todos: packet.todos },
              };
            }
          } else {
            items.push({
              type: "todo_list",
              id: packet.toolCallId,
              todoList: { id: packet.toolCallId, todos: packet.todos, isOpen: false },
            });
          }
        } else {
          items.push({
            type: "tool_call",
            id: packet.toolCallId,
            toolCall: {
              id: packet.toolCallId,
              kind: packet.kind,
              title: packet.title,
              description: packet.description,
              command: packet.command,
              status: packet.status,
              rawOutput: packet.rawOutput,
              subagentType: packet.subagentType ?? undefined,
              isNewFile: packet.isNewFile,
              oldContent: packet.oldContent,
              newContent: packet.newContent,
            },
          });
        }
        break;
    }
  }
  return items;
}
```

**The critical change:** Both consumers call `parsePacket()` on the raw data.
There is no other packet-processing code path. Tool detection, field extraction,
and path sanitization happen exactly once, identically, in `parsePacket`.

---

## 5. `ToolCallKind` Type Update

The `displayTypes.ts` type needs to match what the backend actually sends:

```typescript
// Before:
export type ToolCallKind = "execute" | "read" | "task" | "other";

// After:
export type ToolCallKind = "search" | "read" | "execute" | "edit" | "task" | "other";
```

This eliminates the `kind === "edit" ? "other" : kind` workaround scattered
across 4 functions.

---

## 6. Additional Fixes (Embedded in §3 Helper Functions)

All of these are already implemented in the helper functions defined in §3 above:

- **Line number regex**: Changed from `/^\d{5}\| /gm` to `/^\d+\| /gm` (in `extractFileContent`)
- **Task metadata stripping**: Changed from `indexOf("<task_metadata>")` to
  `/<task_metadata>[\s\S]*?<\/task_metadata>/g` regex (in `extractTaskOutput`)
- **Title trailing spaces**: Removed — titles like `"Reading"` no longer have trailing
  spaces. Concatenation (`${title} ${filePath}`) is the renderer's responsibility (in `buildTitle`)

---

## 7. Path Sanitization Test Cases

```typescript
// ── stripSessionPrefix ──────────────────────────────────────────────

// Local: sandboxes/uuid/sessions/uuid
"/Users/wenxi-onyx/data/sandboxes/b29c196e-fa14-46b8-8182-ff4a7f67b47b/sessions/9c7662c1-785f-4f1c-b9e0-9021ddbf2893/outputs/web/AGENTS.md"
→ "outputs/web/AGENTS.md"

// Local: files/ directory under session root
"/Users/wenxi-onyx/data/sandboxes/b29c196e-fa14-46b8-8182-ff4a7f67b47b/sessions/9c7662c1-785f-4f1c-b9e0-9021ddbf2893/files/linear/Engineering/ticket.json"
→ "files/linear/Engineering/ticket.json"

// Kubernetes: sessions/uuid (no sandboxes prefix)
"/workspace/sessions/9c7662c1-785f-4f1c-b9e0-9021ddbf2893/outputs/web/page.tsx"
→ "outputs/web/page.tsx"

// Already relative — unchanged
"outputs/web/page.tsx"
→ "outputs/web/page.tsx"

// Title field (missing leading /)
"Users/wenxi-onyx/data/sandboxes/b29c196e-fa14-46b8-8182-ff4a7f67b47b/sessions/9c7662c1-785f-4f1c-b9e0-9021ddbf2893/outputs/web/page.tsx"
→ "outputs/web/page.tsx"

// Sandbox UUID without hyphens (edge case — still valid hex)
"/data/sandboxes/abcdef1234567890abcdef1234567890ab/sessions/abcdef1234567890abcdef1234567890ab/file.txt"
→ "file.txt"

// ── sanitizePathsInText ─────────────────────────────────────────────

// Bash command with cd (local path, sandboxes+sessions)
"cd /Users/wenxi-onyx/data/sandboxes/abc-123/sessions/def-456/outputs/web && python3 prepare.py"
→ "cd outputs/web && python3 prepare.py"

// Bash command with chmod + execute (two paths in one command)
"chmod +x /Users/wenxi/data/sandboxes/abc/sessions/def/outputs/web/prepare.sh && /Users/wenxi/data/sandboxes/abc/sessions/def/outputs/web/prepare.sh"
→ "chmod +x outputs/web/prepare.sh && outputs/web/prepare.sh"

// ls output listing session paths (kubernetes)
"/workspace/sessions/def-456/outputs/web/page.tsx\n/workspace/sessions/def-456/outputs/web/globals.css"
→ "outputs/web/page.tsx\noutputs/web/globals.css"

// Grep/find output with local paths
"find /Users/wenxi/data/sandboxes/abc/sessions/def/files/linear -type d"
→ "find files/linear -type d"

// Text with no sandbox/session paths — unchanged
"total 0\ndrwxr-xr-x@ 3 wenxi-onyx  staff  96 Jan 21 15:18 .\n"
→ "total 0\ndrwxr-xr-x@ 3 wenxi-onyx  staff  96 Jan 21 15:18 .\n"

// Error messages containing paths
"Error: ENOENT: no such file or directory, open '/workspace/sessions/abc-123/outputs/web/missing.tsx'"
→ "Error: ENOENT: no such file or directory, open 'outputs/web/missing.tsx'"
```

---

## 8. File Plan

| File | Action | Description |
|------|--------|-------------|
| `utils/pathSanitizer.ts` | **CREATE** | `stripSessionPrefix` + `sanitizePathsInText` |
| `utils/packetTypes.ts` | **CREATE** | Type definitions (`ToolName`, `ParsedPacket` union) + raw field accessor helpers. Re-exports `ToolCallKind` and `ToolCallStatus` from `displayTypes.ts` |
| `utils/parsePacket.ts` | **CREATE** | Single `parsePacket()` entry point + all helper functions (`extractText`, `normalizeStatus`, `extractDiffData`, `buildTitle`, `buildDescription`, `extractRawOutputText`, `extractTodos`, `extractTaskOutput`, etc.) |
| `utils/streamItemHelpers.ts` | **REDUCE** | Keep only `genId()` and `isWorkingToolCall()` (used by `BuildMessageList.tsx` for display grouping — not a packet concern) |
| `types/displayTypes.ts` | **MODIFY** | Add `"search"` and `"edit"` to `ToolCallKind` |
| `hooks/useBuildStreaming.ts` | **MODIFY** | Use `parsePacket()`, remove local `getFilePath()` |
| `hooks/useBuildSessionStore.ts` | **MODIFY** | Use `parsePacket()` in `convertMessagesToStreamItems()` |
| `utils/pathSanitizer.test.ts` | **CREATE** | Exhaustive test suite for both sanitizers |

---

## 9. Migration Steps

1. **Create `pathSanitizer.ts`** with both functions + unit tests.
   This is standalone — no dependencies, can be validated immediately.

2. **Create `packetTypes.ts`** with all type definitions.
   Update `ToolCallKind` in `displayTypes.ts`.

3. **Create `parsePacket.ts`** importing from the above two files.
   This replaces all of `streamItemHelpers.ts` except `genId()`.

4. **Update `useBuildStreaming.ts`** to use `parsePacket()`.
   Delete the local `getFilePath()` function.
   The output file detector logic now uses `packet.filePath` (pre-sanitized).

5. **Update `useBuildSessionStore.ts`** to use `parsePacket()` in
   `convertMessagesToStreamItems()`.
   Delete the inline tool name extraction (`metadata.title`).

6. **Reduce `streamItemHelpers.ts`** to only `genId()` and `isWorkingToolCall()`.
   Delete all other exports (they now live in `parsePacket.ts`).

7. **Delete `packet-processing-refactor.md`** (this document — it's done).

---

## 10. Key Invariant

After this refactor, the following must be true:

> **Every string displayed to the user that originated from a backend packet
> has been processed through either `stripSessionPrefix` (structured path fields)
> or `sanitizePathsInText` (freeform text fields) before reaching any React
> component.**

No raw `Record<string, unknown>` access exists outside of `parsePacket.ts`.
No path sanitization logic exists outside of `pathSanitizer.ts`.
No tool-name detection logic exists outside of `parsePacket.ts`.
