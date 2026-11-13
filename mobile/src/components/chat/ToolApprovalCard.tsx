// A chat tool call's approval request. RN counterpart of web's ApprovalCard (chat scope): a pending
// request shows its arguments and decisions; a decided one leaves a one-line record.
import { memo, useEffect, useRef, useState } from "react";
import { AccessibilityInfo, Platform, Pressable, View } from "react-native";

import { postApprovalDecision } from "@/api/chat/approvals";
import { isApiError } from "@/api/errors";
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
import { useReducedMotion } from "@/hooks/useReducedMotion";
import SvgCheckSquare from "@/icons/check-square";
import SvgChevronDown from "@/icons/chevron-down";
import SvgClock from "@/icons/clock";
import SvgLoader from "@/icons/loader";
import SvgX from "@/icons/x";

const RECORD_PREFIX: Record<Exclude<ApprovalStatus, "pending">, string> = {
  approved: "Approved",
  approvedForSession: "Approved for this chat",
  rejected: "Not approved",
  expired: "Timed out",
  disabled: "Disabled",
  closed: "No longer waiting",
};

function formatDeadline(expiresAt: string): string | null {
  const deadline = new Date(expiresAt);
  if (Number.isNaN(deadline.getTime())) return null;
  return `Approve by ${deadline.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  })}`;
}

// iOS has no live regions; Android reads `accessibilityLiveRegion` instead.
function announce(message: string): void {
  if (Platform.OS === "ios")
    AccessibilityInfo.announceForAccessibility(message);
}

function ToolApprovalCardComponent({ approval }: { approval: ToolApproval }) {
  const { request, status } = approval;
  const reduceMotion = useReducedMotion();
  const [isOpen, setIsOpen] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);

  const headline = request.display_name || request.tool_name;
  const header = `Approval requested: ${headline}`;
  const record =
    status === "pending" ? null : `${RECORD_PREFIX[status]}: ${headline}`;
  const deadline = formatDeadline(request.expires_at);

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

  // The decided status shows at once; the resolution packet then confirms it.
  async function decide(decision: ApprovalDecision) {
    const { recordStatus } = useToolApprovalUi.getState();
    setSubmitting(true);
    setError(false);
    try {
      recordStatus(
        request.approval_id,
        decidedStatus(
          await postApprovalDecision(request.approval_id, decision),
        ),
      );
    } catch (cause) {
      if (isApiError(cause) && (cause.status === 409 || cause.status === 404)) {
        recordStatus(request.approval_id, "closed");
      } else {
        console.warn("Could not submit the approval decision", cause);
        setError(true);
        setIsOpen(true);
        announce("Could not submit your decision. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
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

  return (
    <View
      testID="tool-approval-card"
      className="overflow-hidden rounded-08 border border-status-info-02 bg-background-neutral-00"
    >
      <Pressable
        onPress={() => setIsOpen((open) => !open)}
        accessibilityRole="button"
        accessibilityLiveRegion="polite"
        accessibilityLabel={deadline ? `${header}. ${deadline}` : header}
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
        {deadline ? (
          <Text font="secondary-body" color="text-03" nowrap>
            {deadline}
          </Text>
        ) : null}
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
}

// Approvals rebuild on every streamed packet; the request and status stay the same until a change.
export const ToolApprovalCard = memo(
  ToolApprovalCardComponent,
  (prev, next) =>
    prev.approval.request === next.approval.request &&
    prev.approval.status === next.approval.status,
);
