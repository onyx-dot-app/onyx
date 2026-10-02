// A `propose_scheduled_task` tool the agent calls to suggest a recurring task.
// It creates nothing. The completed tool call persists into the build message,
// the api-server renders an approval card from it, and creating the real task
// happens only when the user approves (see the proposals decision endpoint).
//
// Unlike `connect-app.ts` this does NOT call `context.ask`: parking the turn
// would cap the user's review at SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS (180s),
// and a permission answer cannot carry the user's edits back to the agent.
// The tool returns immediately and the turn ends normally.
//
// Module resolution: this file lives in /workspace/opencode-plugins, which has
// no node_modules, so a bare runtime `import` of the SDK can't resolve. The type
// import is erased; the `tool` helper is loaded at runtime by absolute path from
// opencode's bundled SDK (same approach as the other plugins here).

import type { Plugin } from "@opencode-ai/plugin";
import type { tool as ToolFactory } from "@opencode-ai/plugin/tool";

const SDK_TOOL_PATHS = [
  "/home/sandbox/.opencode/node_modules/@opencode-ai/plugin/dist/tool.js",
  "/home/sandbox/.config/opencode/node_modules/@opencode-ai/plugin/dist/tool.js",
];

async function loadToolFactory(): Promise<typeof ToolFactory> {
  for (const path of SDK_TOOL_PATHS) {
    try {
      return (await import(path)).tool;
    } catch {
      continue;
    }
  }
  throw new Error("could not resolve the @opencode-ai/plugin tool helper");
}

export const ScheduledTaskProposal: Plugin = async () => {
  const tool = await loadToolFactory();

  return {
    tool: {
      propose_scheduled_task: tool({
        description:
          "Propose a recurring scheduled task for the user to approve. " +
          "This does NOT create the task: it shows the user a card they " +
          "review, edit, and approve themselves. Call it once, then continue " +
          "and tell the user you have proposed it. Do not wait for a decision, " +
          "do not ask whether they approved, do not claim the task exists, and " +
          "do not call this again for the same request. The user may change any " +
          "field before approving, so describe what you proposed rather than " +
          "what will run. The prompt runs later with no chat history, so it must " +
          "be self-contained.",
        args: {
          name: tool.schema
            .string()
            .describe("Short label for the task, e.g. 'Weekday backlog digest'"),
          prompt: tool.schema
            .string()
            .describe(
              "The instruction to run on each fire. Must stand alone: it runs " +
                "in a fresh session with none of this conversation's context."
            ),
          schedule_mode: tool.schema
            .enum(["interval", "daily_weekly"])
            .describe(
              "'interval' repeats every N minutes/hours. 'daily_weekly' runs " +
                "at a time of day on chosen weekdays. No other mode is supported."
            ),
          interval_unit: tool.schema
            .enum(["minutes", "hours"])
            .optional()
            .describe("interval mode only"),
          interval_every: tool.schema
            .number()
            .int()
            .min(1)
            .optional()
            .describe(
              "interval mode only. Max 59 for minutes and 23 for hours; use a " +
                "larger unit instead of exceeding those."
            ),
          time_of_day: tool.schema
            .string()
            .optional()
            .describe(
              "daily_weekly mode only. 24-hour HH:MM in the USER'S LOCAL time. " +
                "Never convert to UTC; the app does that when they approve."
            ),
          weekdays: tool.schema
            .array(tool.schema.number().int().min(0).max(6))
            .optional()
            .describe(
              "daily_weekly mode only. 0 is Sunday through 6 is Saturday. " +
                "Omit or leave empty for every day."
            ),
        },
        async execute() {
          // Deliberately inert. The args are what matter: they persist with the
          // tool call and seed the approval card.
          return (
            "Proposal shown to the user for review. They may edit any field " +
            "before approving, so the final task may differ from what you " +
            "proposed. Nothing is scheduled yet and you will not be told the " +
            "outcome in this turn. Tell the user you have proposed it and that " +
            "it will run once they approve the card."
          );
        },
      }),
    },
  };
};

export default ScheduledTaskProposal;
