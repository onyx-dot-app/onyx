// Steers the agent to wrap up when a turn exceeds its soft time budget: past
// the deadlines stamped by the backend at turn start (`stamp_turn_deadline`),
// tool results carry a converge notice, escalating to finish-now near the
// hard cap. Nothing in flight is killed — the api-server's hard cap does the
// aborting. Missing/unreadable/stale stamp → inert.

import type { Plugin } from "@opencode-ai/plugin";

const BUDGET_FILE = ".onyx-turn-budget.json";

const NOTICE_INTERVAL_MS = 60_000;

function convergeNotice(minutesLeft: number): string {
  return (
    `[Onyx turn budget] About ${minutesLeft} minute(s) of turn budget left. ` +
    "Stop opening new research or subagent work; converge on the final " +
    "deliverable with what you already have."
  );
}

const FINISH_NOW_NOTICE =
  "[Onyx turn budget] Finish now: write any pending outputs to disk and " +
  "reply immediately with what was delivered and what remains. Do not report " +
  "work as complete if it is not — separate what is done from what remains. " +
  "If you are a subagent, return your findings immediately.";

interface TurnDeadlineStamp {
  soft_deadline_epoch_ms?: unknown;
  final_deadline_epoch_ms?: unknown;
  stale_after_epoch_ms?: unknown;
}

export default (async ({ directory }) => {
  const stampPath = `${directory}/${BUDGET_FILE}`;
  let lastNoticeAtMs = 0;

  async function currentNotice(): Promise<string | null> {
    let stamp: TurnDeadlineStamp;
    try {
      stamp = (await Bun.file(stampPath).json()) as TurnDeadlineStamp;
    } catch {
      return null;
    }
    const soft = stamp.soft_deadline_epoch_ms;
    const final = stamp.final_deadline_epoch_ms;
    const stale = stamp.stale_after_epoch_ms;
    if (
      typeof soft !== "number" ||
      typeof final !== "number" ||
      typeof stale !== "number"
    ) {
      return null;
    }
    const now = Date.now();
    // A stamp past stale_after is from an already-capped turn whose restamp
    // failed — never nag a fresh turn off it.
    if (now <= soft || now >= stale) return null;
    if (now >= final) return FINISH_NOW_NOTICE;
    return convergeNotice(Math.max(1, Math.ceil((stale - now) / 60_000)));
  }

  return {
    "tool.execute.after": async (_input, output) => {
      // undefined on a failed task subtask (opencode Effect.catchCause path).
      if (!output) return;
      const notice = await currentNotice();
      if (notice === null) return;
      const now = Date.now();
      if (now - lastNoticeAtMs < NOTICE_INTERVAL_MS) return;
      lastNoticeAtMs = now;
      // Built-in tools render `.output`; MCP results are rebuilt from
      // `.content` after this hook, so cover both.
      output.output = `${output.output ?? ""}\n\n${notice}`;
      const content = (output as { content?: unknown }).content;
      if (Array.isArray(content)) {
        content.push({ type: "text", text: notice });
      }
    },
  };
}) satisfies Plugin;
