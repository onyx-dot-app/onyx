/** The agent tools of every tool family, and their calls read from packets. */
import { PacketType, type Packet } from "@/app/app/services/streamingModels";

export interface AgentTool {
  action: "spawn" | "send" | "interrupt";
  /** The argument that names the agent. */
  nameArg: string;
  /** The argument that holds the text sent to the agent. */
  messageArg: string | null;
}

/** The agent tools by the name the model calls them. Each tool family spawns
 *  and messages agents with its own names and arguments. */
const AGENT_TOOLS: ReadonlyMap<string, AgentTool> = new Map([
  [
    "spawn_agent",
    { action: "spawn", nameArg: "task_name", messageArg: "message" },
  ],
  ["agent", { action: "spawn", nameArg: "description", messageArg: "prompt" }],
  [
    "send_message",
    { action: "send", nameArg: "target", messageArg: "message" },
  ],
  [
    "interrupt_agent",
    { action: "interrupt", nameArg: "target", messageArg: null },
  ],
]);

function agentTool(packets: readonly Packet[]): AgentTool | undefined {
  for (const { obj } of packets) {
    if (obj.type === PacketType.CUSTOM_TOOL_START)
      return AGENT_TOOLS.get(obj.tool_name);
  }
  return undefined;
}

export function isAgentToolPacket(packet: Packet): boolean {
  return agentTool([packet]) !== undefined;
}

/** A spawn call's first packet: consecutive spawns of a turn form a group. */
export function isSpawnPacket(packet: Packet): boolean {
  return agentTool([packet])?.action === "spawn";
}

function stringArg(args: Record<string, unknown>, key: string): string {
  const value = args[key];
  return typeof value === "string" ? value.trim() : "";
}

/** One agent tool call, read from its packets. */
export interface AgentToolCall {
  action: AgentTool["action"];
  name: string;
  message: string;
  failed: boolean;
  isComplete: boolean;
}

/** Each agent tool call in the packets, by its tab, in order. */
export function agentToolCalls(packets: readonly Packet[]): AgentToolCall[] {
  const byTab = new Map<number, Packet[]>();
  for (const packet of packets) {
    const tab = packet.placement.tab_index ?? 0;
    byTab.set(tab, [...(byTab.get(tab) ?? []), packet]);
  }
  return [...byTab.entries()]
    .sort(([a], [b]) => a - b)
    .flatMap(([, tabPackets]) => {
      const tool = agentTool(tabPackets);
      if (!tool) return [];
      const call: AgentToolCall = {
        action: tool.action,
        name: "",
        message: "",
        failed: false,
        isComplete: false,
      };
      for (const { obj } of tabPackets) {
        if (obj.type === PacketType.CUSTOM_TOOL_ARGS) {
          call.name =
            stringArg(obj.tool_args, tool.nameArg) ||
            // The Claude family names the target `to`.
            (tool.action === "send" ? stringArg(obj.tool_args, "to") : "");
          if (tool.messageArg)
            call.message = stringArg(obj.tool_args, tool.messageArg);
        } else if (obj.type === PacketType.CUSTOM_TOOL_DELTA && obj.error) {
          call.failed = true;
        } else if (obj.type === PacketType.ERROR) {
          call.failed = true;
          call.isComplete = true;
        } else if (obj.type === PacketType.SECTION_END) {
          call.isComplete = true;
        }
      }
      return [call];
    });
}
