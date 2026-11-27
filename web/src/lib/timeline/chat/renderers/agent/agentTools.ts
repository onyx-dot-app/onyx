/** The agent tools of every tool family, and their calls read from packets. */
import {
  readCustomToolCall,
  PacketType,
  type Packet,
} from "@/app/app/services/streamingModels";

export interface AgentTool {
  action: "spawn" | "send" | "interrupt";
  /** The argument that names the agent. */
  nameArg: string;
  /** Whether the server turns each `/` of the name into `-` for the
   *  agent's path, as it does for a description. */
  slashesToDashes?: boolean;
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
  [
    "agent",
    {
      action: "spawn",
      nameArg: "description",
      messageArg: "prompt",
      slashesToDashes: true,
    },
  ],
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
  /** The last part of the spawned agent's path. */
  agentName: string;
  message: string;
  failed: boolean;
  isComplete: boolean;
}

/** Each agent tool call in the packets, by its turn and tab, in stream order. */
export function agentToolCalls(packets: readonly Packet[]): AgentToolCall[] {
  const byCall = new Map<string, Packet[]>();
  for (const packet of packets) {
    const { turn_index, tab_index } = packet.placement;
    const call = `${turn_index}-${tab_index ?? 0}`;
    const group = byCall.get(call);
    if (group) group.push(packet);
    else byCall.set(call, [packet]);
  }
  return [...byCall.values()].flatMap((tabPackets) => {
    const tool = agentTool(tabPackets);
    if (!tool) return [];
    const { args, failed, isComplete } = readCustomToolCall(tabPackets);
    const name = args
      ? stringArg(args, tool.nameArg) ||
        // The Claude family names the target `to`.
        (tool.action === "send" ? stringArg(args, "to") : "")
      : "";
    const call: AgentToolCall = {
      action: tool.action,
      name,
      agentName: tool.slashesToDashes ? name.replaceAll("/", "-") : name,
      message: args && tool.messageArg ? stringArg(args, tool.messageArg) : "",
      failed,
      isComplete,
    };
    return [call];
  });
}
