"use client";

import { memo } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@opal/utils";
import { Content, Section } from "@opal/layouts";
import { getModelIcon } from "@/lib/languageModels/utils";
import type { MultiModelResponse } from "@/lib/timeline/chat/message/types";
import { useNudgedCard, useToolApprovalDecision } from "@/lib/chat/hooks";
import type { ToolApproval } from "@/lib/chat/toolApprovals";
import ApprovalCard from "@/sections/approvals/ApprovalCard";

interface ToolApprovalCardProps {
  approval: ToolApproval;
  /** The answer of a multi-model turn that made the request. */
  model?: Pick<MultiModelResponse, "provider" | "modelName" | "displayName">;
}

/** A chat tool call's approval request on the shared approval card. */
function ToolApprovalCard({ approval, model }: ToolApprovalCardProps) {
  const { request } = approval;
  const t = useTranslations("chat.messages.toolApproval");
  const card = useNudgedCard(request.approval_id);
  const decide = useToolApprovalDecision(request.approval_id);

  const agentRequest =
    request.agent_name === null
      ? undefined
      : t("agentRequest", {
          agent: request.agent_name,
          tool: request.display_name,
        });
  // Names the request's source in the trailing region, where cards from
  // several answers and agents meet.
  const sourceTitle = model?.displayName ?? agentRequest;

  return (
    <div
      ref={card.ref}
      data-testid="tool-approval-card"
      className={cn(card.shaking && "motion-safe:animate-shake")}
      onAnimationEnd={card.onAnimationEnd}
    >
      <Section gap={0.5} alignItems="stretch" height="auto">
        {approval.status === "pending" && sourceTitle && (
          <Content
            font="secondary-body"
            titleColor="text-03"
            icon={model && getModelIcon(model.provider, model.modelName)}
            title={sourceTitle}
            description={model && agentRequest}
          />
        )}
        <ApprovalCard
          actions={[{ id: request.tool_name, name: request.display_name }]}
          appName={request.app_name ?? undefined}
          payload={request.arguments}
          expiresAt={request.expires_at}
          sessionScope={request.can_approve_for_command ? "command" : "chat"}
          canApproveForSession={
            request.can_approve_for_command === true ||
            request.can_approve_for_chat !== false
          }
          status={approval.status}
          onDecide={decide}
        />
      </Section>
    </div>
  );
}

// Callers rebuild approvals on every streamed packet; the request object,
// status and model stay the same until something changes.
export default memo(
  ToolApprovalCard,
  (prev, next) =>
    prev.approval.request === next.approval.request &&
    prev.approval.status === next.approval.status &&
    prev.model?.displayName === next.model?.displayName &&
    prev.model?.provider === next.model?.provider &&
    prev.model?.modelName === next.model?.modelName
);
