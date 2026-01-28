/**
 * Parse Packet
 *
 * Single entry point for converting raw ACP packets into strongly-typed
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
  const packetType = p.type as string | undefined;

  switch (packetType) {
    case "agent_message_chunk": // Live SSE
    case "agent_message": // DB-stored format
      return { type: "text_chunk", text: extractText(p.content) };

    case "agent_thought_chunk": // Live SSE
    case "agent_thought": // DB-stored format
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

/** Extract text from ACP content structure (string, {type,text}, or array) */
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
  if (
    (toolName === "glob" || toolName === "grep" || kind === "search") &&
    ri?.pattern &&
    typeof ri.pattern === "string"
  ) {
    return ri.pattern as string;
  }
  return buildTitle(toolName, kind, true);
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
  const rawCommand = (ri?.command ?? "") as string;
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
  const taskOutput =
    toolName === "task" && status === "completed"
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
    isNewFile:
      diffData.oldText || diffData.newText
        ? diffData.isNewFile
        : patchInfo?.isNew ?? diffData.isNewFile,
    oldContent: diffData.oldText,
    newContent: diffData.newText,
    todos,
    taskOutput,
  };
}
