"use client";

import { useEffect, useRef, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { useSWRConfig } from "swr";

import { Button, Collapsible, Text, Tooltip } from "@opal/components";
import { cn } from "@opal/utils";
import {
  SvgClock,
  SvgX,
  SvgCheckSquare,
  SvgChevronDown,
  SvgLoader,
} from "@opal/icons";
import {
  ApprovalConflictError,
  postApprovalDecision,
} from "@/app/craft/services/apiServices";
import {
  ApprovalDecision,
  ApprovalSubmitDecision,
  ApprovalView,
} from "@/app/craft/types/approvals";
import PayloadView from "@/app/craft/components/approvals/PayloadView";
import CometEdge from "@/app/craft/components/CometEdge";
import { SWR_KEYS } from "@/lib/swr-keys";

interface ApprovalCardProps {
  approval: ApprovalView;
  defaultOpen?: boolean;
  /** Seed a decided state for Storybook (real approvals start pending). */
  defaultDecision?: Exclude<ApprovalDecision, "EXPIRED"> | null;
}

/** Pending requests show decision controls; outcomes collapse into neutral tool rows. */
export default function ApprovalCard({
  approval,
  defaultOpen = false,
  defaultDecision = null,
}: ApprovalCardProps) {
  const t = useTranslations("craft.approvals");
  const { mutate } = useSWRConfig();
  const format = useFormatter();
  const tActionPolicies = useTranslations("craft.actionPolicies");
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [outcomeOpen, setOutcomeOpen] = useState(false);
  const [decision, setDecision] = useState<ApprovalDecision | null>(
    defaultDecision ?? approval.decision
  );

  // Guards setState after the post-decision SWR revalidation drops
  // this row and the card unmounts mid-await.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const swrKey = SWR_KEYS.buildSessionApprovals(approval.session_id);
  const expired =
    decision === "EXPIRED" || (decision === null && !approval.is_live);
  const decided = decision !== null || expired;
  const approved = decision === "APPROVED";
  const action = approval.actions[0];
  const headline =
    approval.actions.length === 1 && action
      ? t("headline.singleAction", {
          action: action.display_name,
          app: approval.app_name,
        })
      : t("headline.multiAction", {
          count: approval.actions.length,
          app: approval.app_name,
        });
  const headerText = t("header.required", { headline });

  async function submitDecision(choice: ApprovalSubmitDecision) {
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await postApprovalDecision(approval.approval_id, choice);
      if (mountedRef.current) {
        setDecision(choice === "reject" ? "REJECTED" : "APPROVED");
      }
      void mutate(swrKey);
    } catch (e) {
      // 409 = already resolved (by someone else, or expired by the
      // proxy). Refetch immediately to show the server outcome.
      if (e instanceof ApprovalConflictError) {
        if (mountedRef.current) {
          setDecision(null);
        }
        void mutate(swrKey);
        return;
      }
      console.error("Failed to submit approval decision:", e);
      if (mountedRef.current) {
        setDecision(null);
        setErrorMessage(
          e instanceof Error ? e.message : t("submit.errorFallback")
        );
        // Expand so the error message + the payload the user tried to
        // approve are both visible. Avoids the "click Approve in a
        // collapsed card, nothing visible changes" dead end.
        setIsOpen(true);
      }
    } finally {
      if (mountedRef.current) {
        setSubmitting(false);
      }
    }
  }

  const details = (
    <div className="p-2 flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        {approval.actions.map((action) => (
          <div
            key={action.action_type}
            className="flex flex-col gap-0.5 px-3 py-2 rounded-08 bg-background-neutral-01 border-[0.5px] border-border-01"
          >
            <Text font="main-ui-action" color="text-05">
              {action.display_name}
            </Text>
            <Text font="secondary-body" color="text-03">
              {action.description}
            </Text>
          </div>
        ))}
      </div>
      <PayloadView payload={approval.display_payload} />
      {errorMessage && (
        <div className="text-status-error-05">
          <Text font="secondary-body" color="inherit">
            {errorMessage}
          </Text>
        </div>
      )}
    </div>
  );

  if (decided) {
    const StatusIcon = expired ? SvgClock : approved ? SvgCheckSquare : SvgX;
    return (
      <Collapsible.Root open={outcomeOpen} onOpenChange={setOutcomeOpen}>
        <Collapsible.Trigger className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-start transition-colors hover:bg-background-tint-02">
          <StatusIcon className="size-4 shrink-0 stroke-text-03" />
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <Text
              font="main-ui-muted"
              color="text-04"
              wordWrap="wrap-break-word"
            >
              {headline}
            </Text>
            <Text
              font="secondary-body"
              color="text-03"
              wordWrap="wrap-break-word"
            >
              {expired
                ? tActionPolicies("expired")
                : approved
                  ? t("status.approved")
                  : tActionPolicies("rejected")}
            </Text>
          </span>
          <SvgChevronDown
            className={cn(
              "ms-auto size-4 shrink-0 stroke-text-03 transition-transform",
              !outcomeOpen && "-rotate-90"
            )}
          />
        </Collapsible.Trigger>
        <Collapsible.Content>{details}</Collapsible.Content>
      </Collapsible.Root>
    );
  }

  return (
    <CometEdge active tone="info" speedSeconds={3.6}>
      <div className="rounded-08 border border-status-info-03 overflow-hidden bg-background-neutral-00 transition-colors">
        <Collapsible.Root open={isOpen} onOpenChange={setIsOpen}>
          <div
            className={cn(
              "flex items-center gap-1 pe-2 transition-colors",
              "has-[[data-approval-trigger]:hover]:bg-background-tint-02"
            )}
          >
            <Collapsible.Trigger asChild>
              <button
                data-approval-trigger
                className="flex items-center gap-2 min-w-0 flex-1 text-start px-3 py-2"
              >
                <SvgLoader className="size-4 shrink-0 stroke-status-info-05 animate-spin" />
                <Text
                  font="main-ui-muted"
                  color="text-04"
                  wordWrap="whitespace-nowrap"
                >
                  {headerText}
                </Text>
              </button>
            </Collapsible.Trigger>

            <Collapsible.Trigger asChild>
              <button
                data-approval-trigger
                aria-label={
                  isOpen
                    ? t("details.hideAriaLabel")
                    : t("details.showAriaLabel")
                }
                className="p-1.5"
              >
                <SvgChevronDown
                  className={cn(
                    "size-4 stroke-text-03 transition-transform duration-150",
                    !isOpen && "-rotate-90"
                  )}
                />
              </button>
            </Collapsible.Trigger>
          </div>
          {approval.expires_at && (
            <div className="px-3 pb-2">
              <Text font="secondary-body" color="text-03">
                {tActionPolicies("deadline", {
                  time: format.dateTime(new Date(approval.expires_at), {
                    hour: "numeric",
                    minute: "2-digit",
                    second: "2-digit",
                  }),
                })}
              </Text>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-end gap-1 px-3 pb-2">
            <Button
              prominence="primary"
              size="sm"
              disabled={submitting}
              onClick={() => void submitDecision("approve_once")}
              aria-label={t("approveOnce.ariaLabel")}
            >
              {t("approveOnce.button")}
            </Button>
            {approval.can_approve_for_session !== false && (
              <Tooltip
                tooltip={t("approveSession.tooltip")}
                delayDuration={200}
              >
                <Button
                  prominence="secondary"
                  size="sm"
                  disabled={submitting}
                  onClick={() => void submitDecision("approve_session")}
                  aria-label={t("approveSession.tooltip")}
                >
                  {t("approveSession.button")}
                </Button>
              </Tooltip>
            )}
            <Button
              prominence="secondary"
              size="sm"
              disabled={submitting}
              onClick={() => void submitDecision("reject")}
              aria-label={t("reject.ariaLabel")}
            >
              {t("reject.button")}
            </Button>
          </div>
          <Collapsible.Content>{details}</Collapsible.Content>
        </Collapsible.Root>
      </div>
    </CometEdge>
  );
}
