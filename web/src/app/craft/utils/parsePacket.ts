/**
 * Parse Packet
 *
 * Single entry point for converting raw sandbox-event packets into strongly-typed
 * ParsedPacket values. All field resolution, tool detection, and path
 * sanitization happen here. Consumers never touch Record<string, unknown>.
 */

import { stripSessionPrefix, sanitizePathsInText } from "./pathSanitizer";
import {
  getRawInput,
  getRawOutput,
  getToolCallId,
  getToolNameRaw,
  type ParsedPacket,
  type ParsedToolCallStart,
  type ParsedToolCallProgress,
  type ParsedArtifact,
  type ToolName,
  type ToolKind,
  type ToolStatus,
} from "./packetTypes";
import type { TodoItem, TodoStatus } from "../types/displayTypes";

export function parsePacket(raw: unknown): ParsedPacket {
  if (!raw || typeof raw !== "object") return { type: "unknown" };
  const p = raw as Record<string, unknown>;
  const packetType =
    (p.type as string | undefined) ??
    (p.sessionUpdate as string | undefined) ??
    (p.session_update as string | undefined);

  switch (packetType) {
    case "agent_message_chunk": // Live SSE
    case "agent_message": // DB-stored format
      return {
        type: "text_chunk",
        text: extractText(p.content),
        ...extractRoutingMeta(p),
      };

    case "agent_thought_chunk": // Live SSE
    case "agent_thought": // DB-stored format
      return {
        type: "thinking_chunk",
        text: extractText(p.content),
        ...extractRoutingMeta(p),
      };

    case "tool_call_start":
      return parseToolCallStart(p);

    case "tool_call_progress":
      return parseToolCallProgress(p);

    case "prompt_response":
      return { type: "prompt_response" };

    case "artifact_created":
      return parseArtifact(p);

    case "approval_requested":
      return {
        type: "approval_requested",
        approvalId: (p.approval_id ?? "") as string,
        sessionId: (p.session_id ?? "") as string,
      };

    case "subagent_started":
      return {
        type: "subagent_started",
        subagentSessionId: (p.subagent_session_id ??
          p.subagentSessionId ??
          "") as string,
        parentSessionId: (p.parent_session_id ?? p.parentSessionId ?? null) as
          | string
          | null,
      };

    case "connect_app_request":
      return {
        type: "connect_app_request",
        requestId: (p.request_id ?? "") as string,
        appSlug: (p.app_slug ?? "") as string,
        reason: (p.reason ?? null) as string | null,
      };

    case "context_usage":
      return {
        type: "context_usage",
        usedTokens: Number(p.used_tokens ?? p.usedTokens ?? 0),
      };

    case "compaction":
      return {
        type: "compaction",
        summary: (p.summary ?? null) as string | null,
      };

    case "error":
      return { type: "error", message: (p.message ?? "") as string };

    default:
      return { type: "unknown" };
  }
}

function extractRoutingMeta(p: Record<string, unknown>): {
  sessionId: string | null;
  parentSessionId: string | null;
} {
  const meta = (p._meta as Record<string, unknown> | undefined) ?? {};
  return {
    sessionId: (meta.sessionId as string | undefined) ?? null,
    parentSessionId: (meta.parentSessionId as string | undefined) ?? null,
  };
}

// ─── Skill Detection ──────────────────────────────────────────────

/**
 * Detect skill-namespaced tool invocations. Opencode emits skill calls with
 * raw names like "skills.brainstorming" or "superpowers:test-driven-development".
 * Returns the skill's leaf name (everything after the last separator) or null.
 */
function detectSkillName(
  p: Record<string, unknown>,
  toolName: ToolName
): string | null {
  if (toolName !== "unknown") return null;
  const rawName = getToolNameRaw(p);
  if (!rawName) return null;
  // Match "namespace:skill" or "namespace.skill" patterns
  const match = rawName.match(/^(skills?|superpowers)[.:]([\w-]+)$/);
  return match?.[2] ?? null;
}

function detectSkillScript(command: string): string | null {
  const match = command.match(/\.opencode\/skills\/([\w-]+)\//);
  if (match?.[1]) return match[1];
  // The github skill invokes the gh CLI directly rather than a bundled script.
  // Any gh call in the sandbox authenticates through the github app's proxy
  // injection, so attributing all of them to the skill is intentional.
  if (/^gh\s/.test(command)) return "github";
  return null;
}

function resolveSkillName(
  p: Record<string, unknown>,
  toolName: ToolName,
  kind: ToolKind,
  ri: Record<string, unknown> | null,
  command: string
): string | null {
  return (
    detectSkillName(p, toolName) ??
    (toolName === "skill" && typeof ri?.name === "string"
      ? (ri.name as string)
      : null) ??
    (kind === "execute" ? detectSkillScript(command) : null)
  );
}

// ─── Tool Name Resolution ─────────────────────────────────────────

const NAME_MAP: Record<string, ToolName> = {
  glob: "glob",
  grep: "grep",
  read: "read",
  write: "write",
  edit: "edit",
  bash: "bash",
  task: "task",
  todowrite: "todowrite",
  todo_write: "todowrite",
  webfetch: "webfetch",
  websearch: "websearch",
  // opencode 1.15.x additions:
  lsp: "lsp",
  apply_patch: "apply_patch",
  applypatch: "apply_patch",
  skill: "skill",
  list: "list",
  ls: "list",
  question: "question",
  invalid: "invalid",
};

function resolveToolName(p: Record<string, unknown>): ToolName {
  const rawName = getToolNameRaw(p);

  if (NAME_MAP[rawName]) return NAME_MAP[rawName];

  // Fallback: detect by rawInput shape (handles title changes on completion)
  const ri = getRawInput(p);
  if (ri?.subagent_type || ri?.subagentType) return "task";
  if (ri?.todos && Array.isArray(ri.todos)) return "todowrite";

  // Detect tools by rawInput fields (opencode agent uses different field names)
  if (ri?.patchText && typeof ri.patchText === "string") return "edit";
  if (ri?.command && typeof ri.command === "string") return "bash";

  // Fallback: use backend-provided kind to infer tool name
  const rawKind = (p.kind as string) ?? null;
  if (rawKind === "execute") return "bash";
  if (rawKind === "read") return "read";
  if (rawKind === "edit" || rawKind === "delete" || rawKind === "move")
    return "edit";
  if (rawKind === "search") return "glob";
  if (rawKind === "task") return "task";
  if (rawKind === "fetch") return "webfetch";

  return "unknown";
}

const TOOL_KIND_MAP: Record<ToolName, ToolKind> = {
  glob: "search",
  grep: "search",
  read: "read",
  write: "edit",
  edit: "edit",
  bash: "execute",
  task: "task",
  todowrite: "other",
  webfetch: "other",
  websearch: "search",
  // opencode 1.15.x additions:
  lsp: "other",
  apply_patch: "edit",
  skill: "other",
  list: "read",
  question: "other",
  invalid: "other",
  unknown: "other",
};

function resolveKind(toolName: ToolName, rawKind: string | null): ToolKind {
  const fromName = TOOL_KIND_MAP[toolName];
  if (fromName !== "other") return fromName;

  // Fall back to backend-provided kind
  if (
    rawKind === "search" ||
    rawKind === "read" ||
    rawKind === "execute" ||
    rawKind === "edit" ||
    rawKind === "task"
  ) {
    return rawKind;
  }
  return "other";
}

// ─── Shared Helpers ───────────────────────────────────────────────

/** Extract text from sandbox event content (string, {type,text}, or array) */
function extractText(content: unknown): string {
  if (!content) return "";
  if (typeof content === "string") return content;
  if (typeof content === "object" && content !== null) {
    const obj = content as Record<string, unknown>;
    if (obj.type === "text" && typeof obj.text === "string") return obj.text;
    if (Array.isArray(content)) {
      return content
        .filter(
          (c: Record<string, unknown>) =>
            c?.type === "text" && typeof c.text === "string"
        )
        .map((c: Record<string, unknown>) => c.text)
        .join("");
    }
    if (typeof obj.text === "string") return obj.text;
  }
  return "";
}

function normalizeStatus(status: string | null | undefined): ToolStatus {
  if (
    status === "pending" ||
    status === "in_progress" ||
    status === "completed" ||
    status === "failed" ||
    status === "cancelled"
  ) {
    return status;
  }
  return "pending";
}

// ─── Edit / Diff Extraction ──────────────────────────────────────

/** Extract oldText and newText from content[].type==="diff" items */
function extractDiffData(content: unknown): {
  oldText: string;
  newText: string;
  isNewFile: boolean;
} {
  if (!Array.isArray(content))
    return { oldText: "", newText: "", isNewFile: true };
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
    if (
      item &&
      typeof item === "object" &&
      (item as Record<string, unknown>).type === "diff"
    ) {
      const diffPath = (item as Record<string, unknown>).path as
        | string
        | undefined;
      if (diffPath) return stripSessionPrefix(diffPath);
    }
  }
  // Final fallback: title field may contain a file path
  const title = p.title as string | undefined;
  if (title && title.includes("/")) return stripSessionPrefix(title);
  return "";
}

// ─── Patch Text Extraction (opencode agent) ─────────────────────

/** Extract file path and new-file flag from opencode's patch format.
 *  Format: "*** Update File: path" or "*** Add File: path" */
function extractPatchInfo(
  patchText: string
): { path: string; isNew: boolean } | null {
  const match = patchText.match(
    /\*\*\*\s+(Update|Add|Delete)\s+File:\s*(.+?)(?:\n|$)/
  );
  if (match?.[2]) {
    return {
      path: stripSessionPrefix(match[2].trim()),
      isNew: match[1] === "Add",
    };
  }
  return null;
}

// ─── Description Builder ─────────────────────────────────────────

function buildDescription(
  toolName: ToolName,
  kind: ToolKind,
  filePath: string,
  ri: Record<string, unknown> | null,
  rawDescription: string
): string {
  // Task tool: spawns a subagent. Read as "Spawning subagent: <description>".
  if (toolName === "task") {
    const taskDescription =
      rawDescription || (typeof ri?.prompt === "string" ? ri.prompt : "");
    return taskDescription
      ? `Spawning subagent: ${sanitizePathsInText(taskDescription)}`
      : "Spawning subagent";
  }
  // Read/edit: show file path. For new-file writes, append a line count
  // so the row reads "Writing  src/app/page.tsx (42 lines)" — useful when
  // the body is empty/collapsed.
  if (kind === "read" || kind === "edit") {
    if (filePath) {
      if (toolName === "write" && typeof ri?.content === "string") {
        const lines = (ri.content as string).split("\n").length;
        return `${filePath} (${lines} lines)`;
      }
      return filePath;
    }
  }
  if (kind === "execute") {
    return sanitizePathsInText(rawDescription);
  }
  // Search: show pattern
  if (
    (toolName === "glob" || toolName === "grep" || kind === "search") &&
    ri?.pattern &&
    typeof ri.pattern === "string"
  ) {
    return ri.pattern as string;
  }
  // Webfetch: show URL
  if (toolName === "webfetch" && ri?.url && typeof ri.url === "string") {
    return ri.url as string;
  }
  // Websearch: show query
  if (toolName === "websearch" && ri?.query && typeof ri.query === "string") {
    return ri.query as string;
  }
  return "";
}

// ─── Title Builder ───────────────────────────────────────────────

function buildTitle(
  toolName: ToolName,
  kind: ToolKind,
  isNewFile: boolean
): string {
  // Edit/write: distinguish "Writing" (new file) vs "Editing" (existing)
  if (kind === "edit") return isNewFile ? "Writing" : "Editing";

  const TITLES: Record<ToolName, string> = {
    glob: "Searching files",
    grep: "Searching content",
    read: "Reading",
    write: "Writing",
    edit: "Editing",
    bash: "Running command",
    task: "Running task",
    todowrite: "Updating todos",
    webfetch: "Fetching web content",
    websearch: "Searching web",
    // opencode 1.15.x additions:
    lsp: "Checking code",
    apply_patch: "Applying patch",
    skill: "Running skill",
    list: "Listing files",
    question: "Asking",
    invalid: "Validating",
    unknown: "Running tool",
  };

  // When toolName is unknown, use kind for a more specific title
  if (toolName === "unknown") {
    const KIND_TITLES: Partial<Record<ToolKind, string>> = {
      search: "Searching",
      read: "Reading",
      execute: "Running command",
      task: "Running task",
    };
    return KIND_TITLES[kind] || TITLES.unknown;
  }

  return TITLES[toolName];
}

// ─── Raw Output Extraction ───────────────────────────────────────

/** Extract the appropriate output text based on tool kind.
 *  Returns raw unsanitized text — caller applies sanitizePathsInText. */
function extractRawOutputText(
  toolName: ToolName,
  kind: ToolKind,
  p: Record<string, unknown>,
  ro: Record<string, unknown> | null
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
        const rec = item as Record<string, unknown> | null;
        if (rec?.type === "diff" && typeof rec.newText === "string")
          return rec.newText as string;
      }
    }
    // Fallback: show patchText from rawInput (opencode agent)
    const ri = getRawInput(p);
    if (ri?.patchText && typeof ri.patchText === "string")
      return ri.patchText as string;
    if (!ro) return "";
    // Prefer output string over JSON dump
    if (typeof ro.output === "string") return ro.output;
    return JSON.stringify(ro, null, 2);
  }
  // Search: files list or output string
  if (toolName === "glob" || toolName === "grep" || kind === "search") {
    if (!ro) return "";
    if (typeof ro.output === "string") return ro.output;
    if (ro.files && Array.isArray(ro.files))
      return (ro.files as string[]).join("\n");
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
      const fileMatch = text.match(
        /<file>\n?([\s\S]*?)\n?\(End of file[^)]*\)\n?<\/file>/
      );
      if (fileMatch?.[1]) {
        return fileMatch[1].replace(/^\d+\| /gm, "");
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
  if (
    status === "pending" ||
    status === "in_progress" ||
    status === "completed"
  )
    return status;
  return "pending";
}

// ─── Task Output Extraction ──────────────────────────────────────

function extractTaskOutput(ro: Record<string, unknown> | null): string | null {
  if (!ro?.output || typeof ro.output !== "string") return null;
  return (
    ro.output.replace(/<task_metadata>[\s\S]*?<\/task_metadata>/g, "").trim() ||
    null
  );
}

function extractTaskSessionId(
  ro: Record<string, unknown> | null
): string | null {
  if (!ro?.output || typeof ro.output !== "string") return null;
  const text = ro.output;
  const taskIdMatch = text.match(/^task_id:\s*([^\s(]+)/m);
  if (taskIdMatch?.[1]) return taskIdMatch[1];
  const metadataMatch = text.match(
    /<task_metadata>[\s\S]*?(?:session_id|task_id):\s*([^\s<]+)[\s\S]*?<\/task_metadata>/i
  );
  return metadataMatch?.[1] ?? null;
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
  const kind = resolveKind(toolName, rawKind);
  const ri = getRawInput(p);
  const meta = (p._meta as Record<string, unknown> | undefined) ?? {};
  const rawCommand = (ri?.command ??
    (toolName === "task" ? ri?.prompt : undefined) ??
    "") as string;
  const rawDescription = (ri?.description ?? "") as string;
  const rawFilePath = (ri?.file_path ??
    ri?.filePath ??
    ri?.path ??
    "") as string;
  const filePath = rawFilePath ? stripSessionPrefix(rawFilePath) : "";
  const command = sanitizePathsInText(rawCommand);
  return {
    type: "tool_call_start",
    toolCallId: getToolCallId(p),
    toolName,
    kind,
    isTodo: toolName === "todowrite",
    title: buildTitle(toolName, kind, true),
    description: buildDescription(toolName, kind, filePath, ri, rawDescription),
    command,
    skillName: resolveSkillName(p, toolName, kind, ri, command),
    subagentType: (ri?.subagent_type ?? ri?.subagentType ?? null) as
      | string
      | null,
    sessionId: (meta.sessionId as string | undefined) ?? null,
    parentSessionId: (meta.parentSessionId as string | undefined) ?? null,
    subagentSessionId: (meta.subagentSessionId as string | undefined) ?? null,
  };
}

function parseToolCallProgress(
  p: Record<string, unknown>
): ParsedToolCallProgress {
  const toolName = resolveToolName(p);
  const rawKind = p.kind as string | null;
  const kind = resolveKind(toolName, rawKind);
  const ri = getRawInput(p);
  const ro = getRawOutput(p);
  const isTodo = toolName === "todowrite";

  // ── Edit-specific (extracted first — isNewFile needed by buildTitle) ──
  const diffData =
    kind === "edit"
      ? extractDiffData(p.content)
      : { oldText: "", newText: "", isNewFile: true };

  // The write tool emits the new file body in rawInput.content (not in a
  // content[].type==="diff" item) so the diff extractor misses it. Pull it
  // directly so DiffBody can render the new file's contents.
  if (
    toolName === "write" &&
    !diffData.newText &&
    typeof ri?.content === "string"
  ) {
    diffData.newText = ri.content as string;
    diffData.isNewFile = true;
  }

  // ── Patch info (opencode agent uses patchText instead of file_path) ──
  const patchInfo =
    kind === "edit" && ri?.patchText && typeof ri.patchText === "string"
      ? extractPatchInfo(ri.patchText as string)
      : null;

  // ── File path (structured field → stripSessionPrefix) ──────────
  const rawFilePath = (ri?.file_path ??
    ri?.filePath ??
    ri?.path ??
    "") as string;
  let filePath = rawFilePath
    ? stripSessionPrefix(rawFilePath)
    : extractDiffPath(p);

  // Fallback: extract from patchText
  if (!filePath && patchInfo) {
    filePath = patchInfo.path;
  }

  // ── Command (freeform → sanitizePathsInText) ──────────────────
  // The task tool carries its subagent prompt in `prompt`, not `command`.
  const rawCommand = (ri?.command ??
    (toolName === "task" ? ri?.prompt : undefined) ??
    "") as string;
  const command = sanitizePathsInText(rawCommand);

  // ── Description ───────────────────────────────────────────────
  const rawDescription = (ri?.description ?? "") as string;
  const description = buildDescription(
    toolName,
    kind,
    filePath,
    ri,
    rawDescription
  );

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
  const subagentType = (ri?.subagent_type ?? ri?.subagentType ?? null) as
    | string
    | null;

  // ── Skill detection ───────────────────────────────────────────
  const skillName = resolveSkillName(p, toolName, kind, ri, command);
  const taskOutput =
    toolName === "task" && status === "completed"
      ? extractTaskOutput(ro)
      : null;

  // ── Subagent routing (from ACP _meta) ─────────────────────────
  const meta = (p._meta as Record<string, unknown> | undefined) ?? {};
  const sessionId = (meta.sessionId as string | undefined) ?? null;
  const parentSessionId = (meta.parentSessionId as string | undefined) ?? null;
  const subagentSessionId =
    (meta.subagentSessionId as string | undefined) ??
    (toolName === "task" ? extractTaskSessionId(ro) : null);

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
    skillName,
    isNewFile:
      diffData.oldText || diffData.newText
        ? diffData.isNewFile
        : (patchInfo?.isNew ?? diffData.isNewFile),
    oldContent: diffData.oldText,
    newContent: diffData.newText,
    todos,
    taskOutput,
    sessionId,
    parentSessionId,
    subagentSessionId,
  };
}
