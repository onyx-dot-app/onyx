// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

import { type ComponentProps, useEffect } from "react";
import { useTranslations } from "next-intl";
import {
  isFailedCustomToolDelta,
  PacketType,
  type CustomToolPacket,
  type Packet,
} from "@/app/app/services/streamingModels";
import type { MessageRenderer } from "@/lib/timeline/chat/message/messageComponents/types";
import { STEP_ICONS } from "@/lib/timeline/icons";

interface SkillTool {
  kind: "read" | "load";
  /** The argument that names the skill. */
  nameArg: string;
}

/** The skill tools by the name the model calls them. Each tool family reads
 *  a skill by its own name. */
const SKILL_TOOLS: ReadonlyMap<string, SkillTool> = new Map([
  ["skills_read", { kind: "read", nameArg: "name" }],
  ["skill", { kind: "read", nameArg: "skill" }],
  ["load_skill", { kind: "load", nameArg: "name" }],
]);

function skillTool(packets: readonly Packet[]): SkillTool | undefined {
  for (const { obj } of packets) {
    if (obj.type === PacketType.CUSTOM_TOOL_START)
      return SKILL_TOOLS.get(obj.tool_name);
  }
  return undefined;
}

export function isSkillToolPacket(packet: Packet): boolean {
  return skillTool([packet]) !== undefined;
}

/**
 * A skill read or load as its own step: the skill icon and a title that
 * names the skill, as T3 Code titles a Claude skill call.
 */
export function SkillToolRenderer({
  packets,
  onComplete,
  children,
}: ComponentProps<MessageRenderer<CustomToolPacket, {}>>) {
  const t = useTranslations("chat.messages.timeline.skill");
  const tool = skillTool(packets);
  let name = "";
  let failed = false;
  let isComplete = false;
  for (const { obj } of packets) {
    if (obj.type === PacketType.CUSTOM_TOOL_ARGS && tool) {
      const value: unknown = obj.tool_args[tool.nameArg];
      if (typeof value === "string") name = value.trim();
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

  const kind = tool?.kind ?? "read";
  const title = (state: "running" | "done" | "failed") =>
    name ? t(`${kind}.${state}`, { name }) : t(`${kind}.${state}Unnamed`);

  return children([
    {
      icon: STEP_ICONS.skill,
      status: title("running"),
      // A call that never ended keeps its running title.
      doneStatus: isComplete ? title(failed ? "failed" : "done") : null,
      supportsCollapsible: true,
      timelineLayout: "timeline",
      content: null,
    },
  ]);
}

export default SkillToolRenderer;
