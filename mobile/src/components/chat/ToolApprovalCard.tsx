// A chat tool call's approval request. RN counterpart of web's ApprovalCard (chat scope): a pending
// request shows its arguments and decisions; a decided one leaves a one-line record.
import { memo, useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Platform, Pressable, View } from "react-native";
import { useQueryClient } from "@tanstack/react-query";

import { postApprovalDecision } from "@/api/chat/approvals";
import { isApiError } from "@/api/errors";
import { ChatStream } from "@/chat/interfaces";
import {
  ApprovalDecision,
  ApprovalStatus,
  decidedStatus,
  ToolApproval,
  useToolApprovalUi,
} from "@/chat/toolApprovals";
import { ApprovalPayload } from "@/components/chat/ApprovalPayload";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Spinner } from "@/components/ui/spinner";
import { Text } from "@/components/ui/text";
import { followUserAnswer } from "@/hooks/followUserAnswer";
import { watchBackgroundAgents } from "@/hooks/useChatSessionController";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import SvgCheckSquare from "@/icons/check-square";
import SvgChevronDown from "@/icons/chevron-down";
import SvgClock from "@/icons/clock";
import SvgLoader from "@/icons/loader";
import SvgX from "@/icons/x";
import { useChatSessionStore } from "@/state/chatSessionStore";
import { useSession } from "@/state/session";

const RECORD_PREFIX: Record<Exclude<ApprovalStatus, "pending">, string> = {
  approved: "Approved",
  approvedForSession: "Approved for this chat",
  rejected: "Not approved",
  disabled: "Disabled",
  closed: "No longer waiting",
};

// iOS has no live regions; Android reads `accessibilityLiveRegion` instead.
function announce(message: string): void {
  if (Platform.OS === "ios")
    AccessibilityInfo.announceForAccessibility(message);
}

function ToolApprovalCardComponent({ approval }: { approval: ToolApproval }) {
  const { request, status } = approval;
  const reduceMotion = useReducedMotion();
  const serverUrl = useSession((state) => state.serverUrl);
  const queryClient = useQueryClient();
  const [isOpen, setIsOpen] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);

  const headline = request.display_name || request.tool_name;
  const header = `Approval requested: ${headline}`;
  // A subagent's request names its agent, since the response shows it among the root's cards.
  const agentLabel = request.agent_name
    ? `${request.agent_name} wants to run ${headline}`
    : null;
  const record =
    status === "pending" ? null : `${RECORD_PREFIX[status]}: ${headline}`;

  const message = record ?? header;
  const announced = useRef<string | null>(null);
  useEffect(() => {
    // A loaded history of decided cards stays quiet; a new wait or a change speaks.
    if (announced.current === null && record !== null) {
      announced.current = message;
      return;
    }
    if (announced.current !== message) announce(message);
    announced.current = message;
  }, [message, record]);

  // The decided status shows at once; the resolution packet then confirms it. A background agent's
  // decision has no stream, so status reads reload the session while the agent runs or waits to
  // resume.
  async function decide(decision: ApprovalDecision) {
    const { recordStatus } = useToolApprovalUi.getState();
    // The card's chat; the user can open another one while the decision is in flight.
    const sessionId = useChatSessionStore.getState().currentSessionId;
    setSubmitting(true);
    setError(false);
    let continuation: ChatStream | null = null;
    let gone = false;
    try {
      const response = await postApprovalDecision(
        request.approval_id,
        decision,
      );
      recordStatus(request.approval_id, decidedStatus(response));
      continuation = response.continuation;
    } catch (cause) {
      if (isApiError(cause) && (cause.status === 409 || cause.status === 404)) {
        recordStatus(request.approval_id, "closed");
        gone = true;
      } else {
        console.warn("Could not submit the approval decision", cause);
        setError(true);
        setIsOpen(true);
        announce("Could not submit your decision. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
    // A background agent's later requests and outcomes show only in the saved session.
    followUserAnswer(
      sessionId,
      continuation,
      serverUrl,
      queryClient,
      !gone && request.agent_name
        ? (id) => void watchBackgroundAgents(id, serverUrl, queryClient)
        : undefined,
    );
  }

  if (record !== null) {
    return (
      <View
        testID="tool-approval-record"
        accessible
        accessibilityLiveRegion="polite"
        accessibilityLabel={record}
        className="flex-row items-center gap-6"
      >
        <Icon
          as={
            status === "approved" || status === "approvedForSession"
              ? SvgCheckSquare
              : status === "rejected" || status === "disabled"
                ? SvgX
                : SvgClock
          }
          size={16}
          className="text-text-04"
        />
        <Text font="main-ui-muted" color="text-04" className="flex-1">
          {record}
        </Text>
      </View>
    );
  }

  const card = (
    <View
      testID="tool-approval-card"
      className="overflow-hidden rounded-08 border border-status-info-02 bg-background-neutral-00"
    >
      <Pressable
        onPress={() => setIsOpen((open) => !open)}
        accessibilityRole="button"
        accessibilityLiveRegion="polite"
        accessibilityLabel={header}
        accessibilityState={{ expanded: isOpen }}
        className="flex-row items-center gap-8 px-12 py-8 active:bg-background-tint-02"
      >
        {reduceMotion ? (
          <Icon as={SvgLoader} size={16} className="text-status-info-05" />
        ) : (
          <Spinner size={16} className="text-status-info-05" />
        )}
        <Text
          font="main-ui-muted"
          color="text-04"
          maxLines={2}
          className="flex-1"
        >
          {header}
        </Text>
        <View style={{ transform: [{ rotate: isOpen ? "0deg" : "-90deg" }] }}>
          <Icon as={SvgChevronDown} size={16} className="text-text-03" />
        </View>
      </Pressable>
      {isOpen ? (
        // Indented under the header text, past the spinner.
        <View className="gap-6 pb-8 pl-36 pr-12">
          <ApprovalPayload payload={request.arguments} />
          {error ? (
            <Text
              font="secondary-body"
              color="status-error-05"
              accessibilityLiveRegion="assertive"
            >
              Could not submit your decision. Try again.
            </Text>
          ) : null}
        </View>
      ) : null}
      <View className="flex-row flex-wrap justify-end gap-4 px-12 pb-12 pt-4">
        <Button
          prominence="primary"
          size="md"
          disabled={submitting}
          onPress={() => void decide("approve_once")}
          accessibilityLabel="Approve this action once"
        >
          Approve once
        </Button>
        <Button
          prominence="secondary"
          size="md"
          disabled={submitting}
          onPress={() => void decide("approve_session")}
          accessibilityLabel="Approve now and run this tool without asking again for the rest of this chat"
        >
          Approve for this chat
        </Button>
        <Button
          prominence="secondary"
          size="md"
          disabled={submitting}
          onPress={() => void decide("reject")}
          accessibilityLabel="Reject this action"
        >
          Reject
        </Button>
      </View>
    </View>
  );
  if (agentLabel === null) return card;
  return (
    <View className="gap-8">
      <Text font="secondary-body" color="text-03">
        {agentLabel}
      </Text>
      {card}
    </View>
  );
}

// Approvals rebuild on every streamed packet; the request and status stay the same until a change.
export const ToolApprovalCard = memo(
  ToolApprovalCardComponent,
  (prev, next) =>
    prev.approval.request === next.approval.request &&
    prev.approval.status === next.approval.status,
);
