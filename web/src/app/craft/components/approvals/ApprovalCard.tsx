"use client";

import { useEffect, useRef, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { useSWRConfig } from "swr";

import { Button, Collapsible, Text, Tooltip } from "@opal/components";
import { cn } from "@opal/utils";
import {
  SvgAlertCircle,
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

// Hold the settled edge so the cross-fade is visible before the row unmounts.
const SETTLE_HOLD_MS = 800;

interface ApprovalCardProps {
  approval: ApprovalView;
  defaultOpen?: boolean;
  /** Seed a decided state for Storybook (real approvals start pending). */
  defaultDecision?: Exclude<ApprovalDecision, "EXPIRED"> | null;
}

/**
 * One row per pending approval. The header names the action, the action row
 * lets the user decide without expanding, and the body shows the per-action
 * breakdown (when multi) and the payload.
 */
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
  // Optimistic decision so the comet settles before the row is refreshed.
  const [decision, setDecision] = useState<ApprovalDecision | null>(
    defaultDecision ?? approval.decision
  );

  // Guards setState after the post-decision SWR revalidation drops
  // this row and the card unmounts mid-await.
  const mountedRef = useRef(true);
  const settleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (settleTimer.current) clearTimeout(settleTimer.current);
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
  const headerText = decided ? headline : t("header.required", { headline });

  async function submitDecision(choice: ApprovalSubmitDecision) {
    setSubmitting(true);
    setErrorMessage(null);
    setDecision(choice === "reject" ? "REJECTED" : "APPROVED");
    try {
      await postApprovalDecision(approval.approval_id, choice);
      if (choice === "approve_session") {
        void mutate(swrKey);
      } else {
        settleTimer.current = setTimeout(() => {
          void mutate(swrKey);
        }, SETTLE_HOLD_MS);
      }
    } catch (e) {
      // 409 = already resolved (by someone else, or expired by the
      // proxy). Refetch immediately so optimistic copy cannot imply this
      // specific decision was accepted.
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

  return (
    <CometEdge
      active={!decided}
      settled={decided}
      tone={decided ? (approved ? "success" : "error") : "info"}
      speedSeconds={3.6}
    >
      <div
        className={cn(
          "rounded-08 border overflow-hidden bg-background-neutral-00 transition-colors",
          decided
            ? approved
              ? "border-status-success-03"
              : "border-status-error-03"
            : "border-status-info-03"
        )}
      >
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
                {decided ? (
                  approved ? (
                    <SvgCheckSquare className="size-4 shrink-0 stroke-status-success-05" />
                  ) : (
                    <SvgAlertCircle className="size-4 shrink-0 stroke-status-error-05" />
                  )
                ) : (
                  <SvgLoader className="size-4 shrink-0 stroke-status-info-05 animate-spin" />
                )}
                <Text
                  font="main-ui-muted"
                  color="text-04"
                  wordWrap="whitespace-nowrap"
                >
                  {headerText}
                </Text>
              </button>
            </Collapsible.Trigger>
            {decided ? (
              <div
                className={cn(
                  "px-2",
                  approved ? "text-status-success-05" : "text-status-error-05"
                )}
              >
                <Text
                  font="main-ui-action"
                  color="inherit"
                  wordWrap="whitespace-nowrap"
                >
                  {t(
                    approved
                      ? "status.approved"
                      : expired
                        ? "status.expired"
                        : "status.rejected"
                  )}
                </Text>
              </div>
            ) : null}
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
          {(expired || decision === "REJECTED") && (
            <div className="px-3 pb-2">
              <Text font="secondary-body" color="status-error-05">
                {tActionPolicies(expired ? "expired" : "rejected")}
              </Text>
            </div>
          )}
          {!decided && approval.expires_at && (
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
          {!decided && (
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
          )}
          <Collapsible.Content>
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
          </Collapsible.Content>
        </Collapsible.Root>
      </div>
    </CometEdge>
  );
}
