// A no-op `connect_app` tool the agent calls to ask the user to connect an org
// app it isn't set up for yet. It does nothing itself: `context.ask` pauses the
// turn and the api-server drives the connect card, then answers allow/deny (see
// serve_client._handle_connect_app_permission).
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

export const ConnectApp: Plugin = async () => {
  const tool = await loadToolFactory();

  return {
    tool: {
      connect_app: tool({
        description:
          "Ask the user to connect an org app you aren't set up to use yet. " +
          "Pass the app's slug (as listed under 'Connectable apps' in AGENTS.md). " +
          "This pauses for the user to connect it. If this returns normally the " +
          "app is connected and you can use it; if it is denied, do not retry — " +
          "offer an alternative.",
        args: {
          app: tool.schema
            .string()
            .describe("Slug of the connectable app, e.g. 'google_calendar'"),
          reason: tool.schema
            .string()
            .optional()
            .describe("One short sentence on why you need it, shown to the user"),
        },
        async execute(args, context) {
          // Blocks until the user answers; resolves on connect, throws on
          // decline. Requires opencode.json `connect_app: "ask"` to prompt.
          try {
            await context.ask({
              permission: "connect_app",
              patterns: [args.app],
              always: [],
              metadata: { app: args.app, reason: args.reason ?? "" },
            });
          } catch {
            // Return a normal result so the agent keeps control and picks an
            // alternative, rather than letting the rejection abort the turn.
            return (
              `The user declined to connect '${args.app}'. Do not retry connecting ` +
              `it; offer an alternative or proceed without it.`
            );
          }
          return `'${args.app}' is connected. You can use it now.`;
        },
      }),
    },
  };
};

export default ConnectApp;
