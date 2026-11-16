"use client";

import { memo, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { cn } from "@opal/utils";
import { Content, Section } from "@opal/layouts";
import { getModelIcon } from "@/lib/languageModels/utils";
import type { MultiModelResponse } from "@/app/app/message/types";
import { FetchError } from "@/lib/fetcher";
import { postChatApprovalDecision } from "@/lib/chat/svc";
import {
  followChatStream,
  refreshChatSession,
} from "@/lib/chat/settleChatSession";
import {
  readChatSessionStatus,
  waitForChatResponseEnd,
} from "@/lib/chat/sessionReadiness";
import type { ChatStream } from "@/app/app/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ApprovalSubmitDecision } from "@/lib/approvals/types";
import {
  decidedStatus,
  type ToolApproval,
  useToolApprovalUi,
} from "@/lib/chat/toolApprovals";
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
  const tReadiness = useTranslations("chat.readiness");
  const nudge = useToolApprovalUi((state) =>
    state.nudge?.approvalId === request.approval_id ? state.nudge.seq : null
  );
  const { mutate } = useSWRConfig();
  const cardRef = useRef<HTMLDivElement>(null);
  const [shaking, setShaking] = useState(false);

  // A blocked send points the user at this card. Clearing the nudge keeps a
  // remounted card from repeating it.
  useEffect(() => {
    if (nudge === null) return;
    useToolApprovalUi.getState().clearNudge(nudge);
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    cardRef.current?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "center",
    });
    // Restart a shake that is still running.
    setShaking(false);
    requestAnimationFrame(() => setShaking(true));
  }, [nudge]);

  // The decided status shows until the resolution packet confirms it. The
  // client follows the stream that the server names as the continuation.
  // Without one, the response continues in a later turn or in a live reader,
  // or an agent continues in the background: a status read hands the chat to
  // its status subscriber, which follows server turns until the chat is idle
  // and then loads the saved session. Incognito does not follow server turns
  // from its status: it waits for the next stream and follows it when it
  // writes its answers. A continuation that already ended is read from the
  // saved answer through a refresh.
  async function submit(decision: ApprovalSubmitDecision) {
    const { recordStatus } = useToolApprovalUi.getState();
    const sessionId = useChatSessionStore.getState().currentSessionId;
    let continuation: ChatStream | null;
    try {
      const response = await postChatApprovalDecision(
        request.approval_id,
        decision
      );
      recordStatus(request.approval_id, decidedStatus(response));
      continuation = response.continuation;
    } catch (cause) {
      // 409 or 404: the request no longer waits for a decision.
      if (
        !(cause instanceof FetchError) ||
        (cause.status !== 409 && cause.status !== 404)
      ) {
        throw cause;
      }
      recordStatus(request.approval_id, "closed");
      if (sessionId === null) return;
      // Another decision can have started the continuation. The read also
      // reaches the status subscriber.
      const status = await readChatSessionStatus(sessionId);
      if (status.is_processing && status.current_stream)
        followChatStream(
          sessionId,
          status.current_stream,
          tReadiness("checkFailed")
        );
      return;
    }
    if (sessionId === null) return;
    if (continuation)
      followChatStream(sessionId, continuation, tReadiness("checkFailed"));
    else if (
      useChatSessionStore.getState().sessions.get(sessionId)?.incognito
    ) {
      const next = await waitForChatResponseEnd(sessionId);
      if (next) {
        followChatStream(sessionId, next, tReadiness("checkFailed"));
        return;
      }
      // A continuation that already ended is read from its saved answer.
      await refreshChatSession(sessionId, tReadiness("checkFailed"));
    } else void mutate(SWR_KEYS.chatSessionStatus(sessionId));
  }

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
      ref={cardRef}
      data-testid="tool-approval-card"
      className={cn(shaking && "motion-safe:animate-shake")}
      onAnimationEnd={(event) => {
        if (event.target === event.currentTarget) setShaking(false);
      }}
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
          payload={request.arguments}
          sessionScope="chat"
          status={approval.status}
          onDecide={submit}
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
