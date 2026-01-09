"use client";

import React, { useCallback, useMemo } from "react";
import { Message, FeedbackType } from "@/app/chat/interfaces";
import { Packet } from "@/app/chat/services/streamingModels";
import { FullChatState } from "@/app/chat/message/messageComponents/interfaces";
import { LlmManager, LlmDescriptor } from "@/lib/hooks";
import AIMessage, {
  AIMessageProps,
  RegenerationFactory,
} from "@/app/chat/message/messageComponents/AIMessage";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { SvgCheck } from "@opal/icons";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";

export interface MultiModelResponse {
  nodeId: number;
  messageId?: number;
  modelName: string;
  packets: Packet[];
  isHighlighted: boolean;
  currentFeedback?: FeedbackType | null;
}

export interface MultiModelResponseViewProps {
  responses: MultiModelResponse[];
  chatState: FullChatState;
  llmManager: LlmManager | null;
  parentMessage?: Message | null;
  onHighlightChange: (nodeId: number) => void;
  onRegenerate?: RegenerationFactory;
}

export default function MultiModelResponseView({
  responses,
  chatState,
  llmManager,
  parentMessage,
  onHighlightChange,
  onRegenerate,
}: MultiModelResponseViewProps) {
  const handleSelectResponse = useCallback(
    (nodeId: number) => {
      onHighlightChange(nodeId);
    },
    [onHighlightChange]
  );

  return (
    <div className="w-full flex gap-4 pb-5 md:pt-5">
      {/* Single Onyx icon on the left */}
      <div className="flex-shrink-0">
        <AgentAvatar agent={chatState.assistant} size={24} />
      </div>

      {/* Content area */}
      <div className="flex-1 flex flex-col gap-4">
        {/* Header */}
        <div className="flex items-center gap-2">
          <Text as="p" secondaryBody text03>
            Answering with {responses.length} models - click to select
          </Text>
        </div>

        {/* Responses Grid - dynamic columns based on number of models */}
        <div
          className={cn(
            "grid grid-cols-1 gap-4",
            responses.length === 2 ? "md:grid-cols-2" : "md:grid-cols-3"
          )}
        >
          {responses.map((response, index) => (
            <MultiModelResponseCard
              key={response.nodeId}
              response={response}
              chatState={chatState}
              llmManager={llmManager}
              parentMessage={parentMessage}
              onSelect={() => handleSelectResponse(response.nodeId)}
              onRegenerate={onRegenerate}
              index={index}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

interface MultiModelResponseCardProps {
  response: MultiModelResponse;
  chatState: FullChatState;
  llmManager: LlmManager | null;
  parentMessage?: Message | null;
  onSelect: () => void;
  onRegenerate?: RegenerationFactory;
  index: number;
}

function MultiModelResponseCard({
  response,
  chatState,
  llmManager,
  parentMessage,
  onSelect,
  onRegenerate,
  index,
}: MultiModelResponseCardProps) {
  const {
    nodeId,
    messageId,
    modelName,
    packets,
    isHighlighted,
    currentFeedback,
  } = response;

  return (
    <div
      className={cn(
        "relative flex flex-col rounded-lg border-2 transition-all cursor-pointer overflow-hidden",
        isHighlighted
          ? "border-action-link-05 bg-background-neutral-subtle"
          : "border-border-02 hover:border-border-01"
      )}
      onClick={onSelect}
    >
      {/* Model Header */}
      <div
        className={cn(
          "flex items-center justify-between px-3 py-2 border-b",
          isHighlighted
            ? "bg-action-link-05/10 border-action-link-05/20"
            : "bg-background-neutral-01 border-border-02"
        )}
      >
        <div className="flex items-center gap-2">
          <Text as="span" secondaryBody text01 className="font-medium">
            {modelName}
          </Text>
        </div>
        {isHighlighted && (
          <div className="flex items-center gap-1 text-action-link-05">
            <SvgCheck className="h-4 w-4" />
            <Text as="span" secondaryBody className="text-action-link-05">
              Selected
            </Text>
          </div>
        )}
      </div>

      {/* Response Content */}
      <div className="flex-1 overflow-auto p-2">
        <AIMessage
          rawPackets={packets}
          chatState={chatState}
          nodeId={nodeId}
          messageId={messageId}
          currentFeedback={currentFeedback}
          llmManager={llmManager}
          parentMessage={parentMessage}
          onRegenerate={onRegenerate}
          hideAvatar
        />
      </div>
    </div>
  );
}
