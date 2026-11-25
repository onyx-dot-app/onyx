import { type ComponentProps, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { codeSpan, markdown } from "@opal/utils";
import {
  isFailedCustomToolDelta,
  PacketType,
  type CustomToolPacket,
  type Packet,
} from "@/app/app/services/streamingModels";
import type { MessageRenderer } from "@/lib/timeline/chat/message/messageComponents/types";
import { STEP_ICONS } from "@/lib/timeline/icons";

interface AgentTool {
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

function stringArg(args: Record<string, unknown>, key: string): string {
  const value = args[key];
  return typeof value === "string" ? value.trim() : "";
}

/**
 * A subagent spawn, message or interrupt as its own step: the agent icon, a
 * title that names the agent, and the text sent to it as the body.
 */
export function AgentToolRenderer({
  packets,
  onComplete,
  children,
}: ComponentProps<MessageRenderer<CustomToolPacket, {}>>) {
  const t = useTranslations("chat.messages.timeline.agentTool");
  const tool = agentTool(packets);
  let name = "";
  let message = "";
  let failed = false;
  let isComplete = false;
  for (const { obj } of packets) {
    if (obj.type === PacketType.CUSTOM_TOOL_ARGS && tool) {
      name =
        stringArg(obj.tool_args, tool.nameArg) ||
        // The Claude family names the target `to`.
        (tool.action === "send" ? stringArg(obj.tool_args, "to") : "");
      if (tool.messageArg) message = stringArg(obj.tool_args, tool.messageArg);
    } else if (
      obj.type === PacketType.CUSTOM_TOOL_DELTA &&
      isFailedCustomToolDelta(obj)
    ) {
      failed = true;
    } else if (obj.type === PacketType.ERROR) {
      failed = true;
      isComplete = true;
    } else if (obj.type === PacketType.SECTION_END) {
      isComplete = true;
    }
  }

  useEffect(() => {
    if (isComplete) onComplete();
  }, [isComplete, onComplete]);

  const action = tool?.action ?? "spawn";
  const title = (state: "running" | "done" | "failed") =>
    name
      ? markdown(t(`${action}.${state}`, { name: codeSpan(name) }))
      : t(`${action}.${state}Unnamed`);

  return children([
    {
      icon: STEP_ICONS.agent,
      status: title("running"),
      doneStatus: title(failed ? "failed" : "done"),
      supportsCollapsible: true,
      timelineLayout: "timeline",
      content: message ? (
        <div className="whitespace-pre-wrap">
          <Text
            as="p"
            font="secondary-body"
            color="text-04"
            wordWrap="wrap-anywhere"
          >
            {message}
          </Text>
        </div>
      ) : null,
    },
  ]);
}

export default AgentToolRenderer;
