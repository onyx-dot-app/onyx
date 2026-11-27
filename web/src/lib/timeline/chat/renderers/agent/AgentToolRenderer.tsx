import { type ComponentProps, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { codeSpan, markdown } from "@opal/utils";
import type { CustomToolPacket } from "@/app/app/services/streamingModels";
import type { MessageRenderer } from "@/lib/timeline/chat/message/messageComponents/types";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { useSpawnedSubagents } from "@/lib/chat/hooks";
import { agentToolCalls } from "@/lib/timeline/chat/renderers/agent/agentTools";
import {
  SubagentCard,
  spawnedSubagentState,
} from "@/lib/timeline/chat/renderers/agent/SubagentCard";

/**
 * A subagent spawn as its card alone, as T3 Code shows one subagent; a
 * message or interrupt as its own step: the agent icon, a title that names
 * the agent, and the text sent to it as the body.
 */
export function AgentToolRenderer({
  packets,
  onComplete,
  children,
}: ComponentProps<MessageRenderer<CustomToolPacket, {}>>) {
  const t = useTranslations("chat.messages.timeline.agentTool");
  const call = agentToolCalls(packets)[0];
  const name = call?.name ?? "";
  const isComplete = call?.isComplete ?? false;
  // A failed spawn, such as one whose name an agent already has, made none
  const {
    agents: [agent],
    available,
    complete,
  } = useSpawnedSubagents(
    call?.action === "spawn" && !call.failed ? [call.agentName] : []
  );

  useEffect(() => {
    if (isComplete) onComplete();
  }, [isComplete, onComplete]);

  const action = call?.action ?? "spawn";
  if (action === "spawn")
    return children([
      {
        icon: STEP_ICONS.agent,
        status: null,
        supportsCollapsible: false,
        timelineLayout: "content",
        content: (
          <SubagentCard
            name={name}
            task={call?.message ?? ""}
            agent={agent}
            state={spawnedSubagentState(
              call?.failed ?? false,
              isComplete,
              agent,
              available && complete
            )}
          />
        ),
      },
    ]);

  const title = (state: "running" | "done" | "failed") =>
    name
      ? markdown(t(`${action}.${state}`, { name: codeSpan(name) }))
      : t(`${action}.${state}Unnamed`);

  return children([
    {
      icon: STEP_ICONS.agent,
      status: title("running"),
      // A call that never ended keeps its running title.
      doneStatus: isComplete ? title(call?.failed ? "failed" : "done") : null,
      supportsCollapsible: true,
      timelineLayout: "timeline",
      content: call?.message ? (
        <div className="whitespace-pre-wrap">
          <Text
            as="p"
            font="secondary-body"
            color="text-04"
            wordWrap="wrap-anywhere"
          >
            {call.message}
          </Text>
        </div>
      ) : null,
    },
  ]);
}

export default AgentToolRenderer;
