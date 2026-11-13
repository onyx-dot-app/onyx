/**
 * Turns Craft stream packets into timeline events.
 *
 * Craft's backend already sends ACP payloads: live SSE events and the rows it
 * saves for history. This adapter reads both, moves Onyx data into
 * `_meta.onyx`, and leaves out what the main timeline does not show.
 */

// Every `unknown` parameter in this file is the decode boundary itself: no
// caller can hand these functions an already-parsed type.
/* oxlint-disable anti-slop/no-unknown-parameters */

import type {
  AcpContentBlock,
  AcpMeta,
  AcpPlanEntry,
  AcpStopReason,
  AcpToolCallContent,
  AcpToolCallLocation,
  AcpToolCallStatus,
  AcpToolKind,
  OnyxMeta,
} from "@/lib/timeline/acp";
import type { TimelineEvent } from "@/lib/timeline/events";

type RawRecord = Record<string, unknown>;

const TOOL_KINDS: readonly AcpToolKind[] = [
  "read",
  "edit",
  "delete",
  "move",
  "search",
  "execute",
  "think",
  "fetch",
  "switch_mode",
  "other",
];
const TOOL_STATUSES: readonly AcpToolCallStatus[] = [
  "pending",
  "in_progress",
  "completed",
  "failed",
];
const STOP_REASONS: readonly AcpStopReason[] = [
  "end_turn",
  "max_tokens",
  "max_turn_requests",
  "refusal",
  "cancelled",
];
const PLAN_STATUSES: readonly AcpPlanEntry["status"][] = [
  "pending",
  "in_progress",
  "completed",
];

function isRecord(value: unknown): value is RawRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function oneOf<T extends string>(
  value: unknown,
  allowed: readonly T[]
): T | undefined {
  return allowed.find((option) => option === value);
}

/**
 * Copies `_meta` and moves Craft's text-part fields into `_meta.onyx`, where
 * the reducer reads them.
 */
function decodeMeta(raw: unknown): AcpMeta | undefined {
  if (!isRecord(raw)) return undefined;
  const { partId, snapshotText, ...rest } = raw;
  const onyx: OnyxMeta = {};
  const part = asString(partId);
  const snapshot = asString(snapshotText);
  if (part !== undefined) onyx.partId = part;
  if (snapshot !== undefined) onyx.snapshotText = snapshot;
  return Object.keys(onyx).length > 0 ? { ...rest, onyx } : rest;
}

/** Craft sends text only; other block types are left out. */
function decodeContentBlock(raw: unknown): AcpContentBlock | undefined {
  if (!isRecord(raw) || raw.type !== "text") return undefined;
  const text = asString(raw.text);
  return text === undefined ? undefined : { type: "text", text };
}

function decodeToolContent(raw: unknown): AcpToolCallContent[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const content: AcpToolCallContent[] = [];
  for (const item of raw) {
    if (!isRecord(item)) continue;
    if (item.type === "diff") {
      const path = asString(item.path);
      const newText = asString(item.newText);
      if (path === undefined || newText === undefined) continue;
      content.push({
        type: "diff",
        path,
        oldText: asString(item.oldText) ?? null,
        newText,
      });
    } else if (item.type === "content") {
      const block = decodeContentBlock(item.content);
      if (block) content.push({ type: "content", content: block });
    } else if (item.type === "terminal") {
      const terminalId = asString(item.terminalId);
      if (terminalId !== undefined)
        content.push({ type: "terminal", terminalId });
    }
  }
  return content;
}

function decodeLocations(raw: unknown): AcpToolCallLocation[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const locations: AcpToolCallLocation[] = [];
  for (const item of raw) {
    if (!isRecord(item)) continue;
    const path = asString(item.path);
    if (path === undefined) continue;
    const line = typeof item.line === "number" ? item.line : null;
    locations.push({ path, line });
  }
  return locations;
}

/** TodoWrite's todos become ACP plan entries. */
function todosToPlan(raw: unknown): AcpPlanEntry[] | undefined {
  if (!isRecord(raw) || !Array.isArray(raw.todos)) return undefined;
  const entries: AcpPlanEntry[] = [];
  for (const todo of raw.todos) {
    if (!isRecord(todo)) continue;
    const content = asString(todo.content);
    const status = oneOf(todo.status, PLAN_STATUSES);
    if (content === undefined || status === undefined) continue;
    const activeForm = asString(todo.activeForm);
    entries.push({
      content,
      // ACP requires a priority; TodoWrite has none, so every entry is equal.
      priority: "medium",
      status,
      ...(activeForm !== undefined && { _meta: { onyx: { activeForm } } }),
    });
  }
  return entries;
}

function decodePlanEntries(raw: unknown): AcpPlanEntry[] {
  if (!Array.isArray(raw)) return [];
  const entries: AcpPlanEntry[] = [];
  for (const item of raw) {
    if (!isRecord(item)) continue;
    const content = asString(item.content);
    const status = oneOf(item.status, PLAN_STATUSES);
    const priority = oneOf(item.priority, ["high", "medium", "low"] as const);
    if (content === undefined || status === undefined || !priority) continue;
    entries.push({ content, priority, status });
  }
  return entries;
}

/** Saved rows and live events name the same update differently. */
function updateKind(packet: RawRecord): string | undefined {
  const sessionUpdate = asString(packet.sessionUpdate);
  if (sessionUpdate) return sessionUpdate;
  switch (packet.type) {
    case "agent_message":
      return "agent_message_chunk";
    case "agent_thought":
      return "agent_thought_chunk";
    case "tool_call_start":
      return "tool_call";
    case "tool_call_progress":
      return "tool_call_update";
    case "agent_plan_update":
      return "plan";
    default:
      return asString(packet.type);
  }
}

function toolEvents(
  packet: RawRecord,
  sessionUpdate: "tool_call" | "tool_call_update",
  meta: AcpMeta | undefined
): TimelineEvent[] {
  const toolCallId = asString(packet.toolCallId);
  if (toolCallId === undefined) return [];

  // TodoWrite is the agent's plan, not a step.
  if (meta?.toolName === "todowrite") {
    const entries = todosToPlan(packet.rawInput);
    return entries
      ? [{ type: "update", update: { sessionUpdate: "plan", entries } }]
      : [];
  }

  const fields = {
    toolCallId,
    kind: oneOf(packet.kind, TOOL_KINDS) ?? null,
    status: oneOf(packet.status, TOOL_STATUSES) ?? null,
    content: decodeToolContent(packet.content) ?? null,
    locations: decodeLocations(packet.locations) ?? null,
    rawInput: packet.rawInput,
    rawOutput: packet.rawOutput,
    _meta: meta,
  };
  const title = asString(packet.title);
  if (sessionUpdate === "tool_call") {
    return [
      {
        type: "update",
        update: { sessionUpdate, title: title ?? "", ...fields },
      },
    ];
  }
  return [
    {
      type: "update",
      update: { sessionUpdate, title: title ?? null, ...fields },
    },
  ];
}

/**
 * Returns the timeline events for one Craft packet, live or saved. Packets the
 * main timeline does not show (subagent events, approvals, artifacts, usage)
 * return no events.
 */
export function craftPacketToEvents(raw: unknown): TimelineEvent[] {
  if (!isRecord(raw)) return [];
  const meta = decodeMeta(raw._meta);

  // A subagent's events belong on its own page.
  if (meta?.sessionId !== undefined && meta.parentSessionId !== undefined) {
    return [];
  }

  const kind = updateKind(raw);
  switch (kind) {
    case "agent_message_chunk":
    case "agent_thought_chunk": {
      // A finished subagent's output, saved for its own page.
      if (raw.source === "task_output") return [];
      const content = decodeContentBlock(raw.content);
      if (!content) return [];
      return [
        {
          type: "update",
          update: { sessionUpdate: kind, content, _meta: meta },
        },
      ];
    }
    case "tool_call":
    case "tool_call_update":
      return toolEvents(raw, kind, meta);
    case "plan":
      return [
        {
          type: "update",
          update: {
            sessionUpdate: "plan",
            entries: decodePlanEntries(raw.entries),
          },
        },
      ];
    case "prompt_response": {
      const stopReason = oneOf(raw.stopReason, STOP_REASONS);
      return stopReason ? [{ type: "stop", stopReason }] : [];
    }
    case "turn_completed":
      // A finished turn's stop arrives as a prompt response; only a failure
      // adds information here.
      return raw.status === "FAILED"
        ? [{ type: "error", message: asString(raw.error_detail) ?? "" }]
        : [];
    case "error":
      return [{ type: "error", message: asString(raw.message) ?? "" }];
    case "compaction":
      return [
        {
          type: "ext",
          notification: {
            method: "_onyx/compaction",
            params: { summary: asString(raw.summary) ?? null },
          },
        },
      ];
    case "connect_app_request": {
      const requestId = asString(raw.request_id);
      const externalAppId = raw.external_app_id;
      if (
        !requestId ||
        typeof externalAppId !== "number" ||
        !Number.isSafeInteger(externalAppId) ||
        externalAppId <= 0
      ) {
        return [];
      }
      return [
        {
          type: "ext",
          notification: {
            method: "_onyx/connect_app_request",
            params: {
              requestId,
              externalAppId,
              reason: asString(raw.reason) ?? null,
            },
          },
        },
      ];
    }
    default:
      return [];
  }
}
