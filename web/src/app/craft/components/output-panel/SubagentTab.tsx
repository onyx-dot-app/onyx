"use client";

import { useCallback, useRef } from "react";
import { Text } from "@opal/components";
import { SvgBubbleText } from "@opal/icons";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import {
  useSubagent,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import CraftToolCard from "@/app/craft/components/tool-cards/CraftToolCard";
import InputBar, { type InputBarHandle } from "@/app/craft/components/InputBar";
import {
  sendSubagentMessageStream,
  processSSEStream,
} from "@/app/craft/services/apiServices";
import { parsePacket } from "@/app/craft/utils/parsePacket";
import { toolCallStateFromProgress } from "@/app/craft/utils/subagentRouting";
import type { SubagentTurn } from "@/app/craft/types/displayTypes";
import type { BuildFile } from "@/app/craft/contexts/UploadFilesContext";

interface SubagentTabProps {
  subagentSessionId: string;
}

interface SubagentTurnViewProps {
  turn: SubagentTurn;
}

/** Renders a single conversation turn: prompt block, tool calls, response. */
function SubagentTurnView({ turn }: SubagentTurnViewProps) {
  return (
    <div className="flex flex-col gap-1">
      {turn.prompt && (
        <div className="flex flex-col gap-1 pb-3">
          <Text font="main-ui-muted" color="text-02">
            Prompt
          </Text>
          <div className="max-h-[14rem] overflow-y-auto whitespace-pre-wrap break-words">
            <Text as="p" font="secondary-body" color="text-04">
              {turn.prompt}
            </Text>
          </div>
        </div>
      )}

      {turn.toolCalls.map((tc) => (
        <CraftToolCard key={tc.id} toolCall={tc} />
      ))}

      {turn.response !== null && (
        <div className="flex flex-col gap-1 pt-3">
          <Text font="main-ui-muted" color="text-02">
            Response
          </Text>
          <div className="max-h-[24rem] overflow-y-auto break-words">
            <MinimalMarkdown content={turn.response} className="text-text-05" />
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * SubagentTab - Body of a subagent transcript panel tab. Shows the subagent's
 * type badge, name, run status, the ordered conversation turns, and a follow-up
 * input for continuing the conversation.
 */
export default function SubagentTab({ subagentSessionId }: SubagentTabProps) {
  const subagent = useSubagent(subagentSessionId);
  const inputRef = useRef<InputBarHandle>(null);

  // Read store actions directly (not via selectors) to avoid re-subscribing.
  const startSubagentFollowupTurn = useBuildSessionStore(
    (state) => state.startSubagentFollowupTurn
  );
  const recordSubagentToolCall = useBuildSessionStore(
    (state) => state.recordSubagentToolCall
  );
  const appendSubagentResponseChunk = useBuildSessionStore(
    (state) => state.appendSubagentResponseChunk
  );
  const markSubagentComplete = useBuildSessionStore(
    (state) => state.markSubagentComplete
  );

  const handleSubmit = useCallback(
    async (message: string, _files: BuildFile[]) => {
      void _files;
      const content = message.trim();
      if (!content) return;

      // Resolve the craft (parent) session id at submit time.
      const sessionId = useBuildSessionStore.getState().currentSessionId;
      if (!sessionId) return;

      startSubagentFollowupTurn(sessionId, subagentSessionId, content);

      try {
        const response = await sendSubagentMessageStream(
          sessionId,
          subagentSessionId,
          content
        );

        await processSSEStream(response, (rawPacket) => {
          const parsed = parsePacket(rawPacket);
          switch (parsed.type) {
            case "tool_call_start":
              // Pill is created from the first progress event.
              break;
            case "tool_call_progress": {
              // Events are already scoped to this subagent — route directly to
              // its last turn without going through global classification.
              recordSubagentToolCall(
                sessionId,
                subagentSessionId,
                "",
                toolCallStateFromProgress(parsed),
                null,
                ""
              );
              break;
            }
            case "text_chunk": {
              if (parsed.text) {
                appendSubagentResponseChunk(
                  sessionId,
                  subagentSessionId,
                  parsed.text
                );
              }
              break;
            }
            case "prompt_response":
              markSubagentComplete(sessionId, subagentSessionId, "done");
              break;
            case "error":
              markSubagentComplete(sessionId, subagentSessionId, "failed");
              break;
            default:
              break;
          }
        });

        // Ensure terminal state even if no explicit prompt_response arrived.
        markSubagentComplete(sessionId, subagentSessionId, "done");
      } catch (err) {
        console.error("[Subagent] Follow-up stream error:", err);
        markSubagentComplete(sessionId, subagentSessionId, "failed");
      }
    },
    [
      subagentSessionId,
      startSubagentFollowupTurn,
      recordSubagentToolCall,
      appendSubagentResponseChunk,
      markSubagentComplete,
    ]
  );

  if (!subagent) {
    return (
      <div className="flex h-full items-center justify-center">
        <Text font="main-ui-body" color="text-02">
          Subagent not found.
        </Text>
      </div>
    );
  }

  const stepCount = subagent.turns.reduce(
    (sum, turn) => sum + turn.toolCalls.length,
    0
  );
  const isRunning = subagent.status === "running";
  const statusLabel = `${subagent.status} · ${stepCount} ${
    stepCount === 1 ? "step" : "steps"
  }`;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-1 flex-col overflow-y-auto p-4">
        <div className="flex items-center gap-2 pb-3">
          <SvgBubbleText className="w-4 h-4 stroke-text-03 shrink-0" />
          {subagent.name && (
            <Text font="main-ui-action" color="text-04" nowrap>
              {subagent.name}
            </Text>
          )}
          <span className="ml-auto">
            <Text
              font={isRunning ? "main-ui-action" : "main-ui-muted"}
              color={isRunning ? "text-04" : "text-02"}
              nowrap
            >
              {statusLabel}
            </Text>
          </span>
        </div>

        <div className="flex flex-col gap-4">
          {subagent.turns.map((turn, idx) => (
            <SubagentTurnView key={idx} turn={turn} />
          ))}
        </div>
      </div>

      <div className="p-3">
        <InputBar
          ref={inputRef}
          onSubmit={handleSubmit}
          isRunning={isRunning}
          placeholder="Reply to this subagent..."
        />
      </div>
    </div>
  );
}
