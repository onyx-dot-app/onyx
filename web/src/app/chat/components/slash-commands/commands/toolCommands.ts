import { ToolSnapshot } from "@/lib/tools/interfaces";
import {
  SlashCommand,
  CommandContext,
} from "@/app/chat/components/slash-commands/types";

function toSlashCommand(name: string): string {
  return (
    "/" +
    name
      .replace(/([a-z])([A-Z])/g, "$1-$2")
      .replace(/[\s_]+/g, "-")
      .replace(/[^a-zA-Z0-9-]/g, "")
      .toLowerCase()
  );
}

// Static tool commands that are always available
const staticToolCommands: SlashCommand[] = [
  {
    command: "/upload",
    description: "Upload files to chat",
    type: "tool" as const,
    execute: (ctx: CommandContext) => {
      ctx.clearInput();
      ctx.triggerFileUpload?.();
    },
  },
];

export function generateToolCommands(
  tools: ToolSnapshot[],
  disabledToolIds: number[] = []
): SlashCommand[] {
  const dynamicCommands = tools
    .filter((tool) => {
      if (!tool.chat_selectable) return false;
      if (tool.mcp_server_id) return false;
      // Don't show commands for disabled tools - user must enable via normal UI
      if (disabledToolIds.includes(tool.id)) return false;
      return true;
    })
    .map((tool) => {
      const displayName = tool.display_name || tool.name;
      return {
        command: toSlashCommand(displayName),
        description: `Use ${displayName}`,
        type: "tool" as const,
        toolId: tool.id,
        execute: (ctx: CommandContext) => {
          ctx.toggleForcedTool(tool.id);
          ctx.clearInput();
        },
      };
    });

  return [...staticToolCommands, ...dynamicCommands];
}
