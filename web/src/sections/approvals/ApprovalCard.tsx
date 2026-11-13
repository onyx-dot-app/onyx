"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";

import { Button, Collapsible, Text, Tooltip } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import {
  SvgCheckSquare,
  SvgChevronDown,
  SvgClock,
  SvgLoader,
  SvgX,
} from "@opal/icons";
import CometEdge from "@/refresh-components/CometEdge";
import type {
  ApprovalStatus,
  ApprovalSubmitDecision,
} from "@/lib/approvals/types";
import PayloadView from "@/sections/approvals/PayloadView";

export interface ApprovalCardAction {
  id: string;
  name: string;
  description?: string;
}

export interface ApprovalCardProps {
  /** The actions the request covers; the first names a single-action card. */
  actions: ApprovalCardAction[];
  /** Omitted for a single action, the headline is the action name alone. */
  appName?: string;
  payload: Record<string, unknown>;
  /** ISO 8601 deadline shown while the request waits. */
  expiresAt?: string | null;
  canApproveForSession?: boolean;
  status: ApprovalStatus;
  /**
   * Submits a decision. A rejected promise shows an error next to the
   * details; the caller reports a decided request through `status`.
   */
  onDecide: (decision: ApprovalSubmitDecision) => Promise<void>;
}

/** A pending request shows its details and decisions; a decided one, one line. */
export default function ApprovalCard({
  actions,
  appName,
  payload,
  expiresAt,
  canApproveForSession = true,
  status,
  onDecide,
}: ApprovalCardProps) {
  const t = useTranslations("common.approvalCard");
  const format = useFormatter();
  const [isOpen, setIsOpen] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);

  async function decide(decision: ApprovalSubmitDecision) {
    setSubmitting(true);
    setError(false);
    try {
      await onDecide(decision);
    } catch (cause) {
      console.error("Failed to submit approval decision:", cause);
      setError(true);
      // Show the error next to the payload the user tried to decide on.
      setIsOpen(true);
    } finally {
      setSubmitting(false);
    }
  }

  const action = actions[0];
  const headline =
    actions.length === 1 && action
      ? appName
        ? t("headline.singleAction", { action: action.name, app: appName })
        : action.name
      : t("headline.multiAction", {
          count: actions.length,
          app: appName ?? "",
        });
  // A decided request leaves a one-line record in the timeline.
  const record =
    status === "pending" ? null : t(`record.${status}`, { headline });

  const single = actions.length === 1;

  const details = (
    // Indented under the header text, past the spinner.
    <div className="ps-9 pe-3 pb-2">
      <Section gap={1.5} alignItems="stretch" height="auto">
        {single
          ? action?.description && (
              <Text
                font="secondary-body"
                color="text-03"
                wordWrap="wrap-anywhere"
              >
                {action.description}
              </Text>
            )
          : actions.map((item) => (
              <Text
                key={item.id}
                font="secondary-body"
                color="text-04"
                wordWrap="wrap-anywhere"
              >
                {item.description
                  ? t("actionWithDescription", {
                      action: item.name,
                      description: item.description,
                    })
                  : item.name}
              </Text>
            ))}
        <PayloadView payload={payload} />
        {error && (
          <Text
            as="p"
            role="alert"
            font="secondary-body"
            color="status-error-05"
          >
            {t("submitError")}
          </Text>
        )}
      </Section>
    </div>
  );

  return (
    <div>
      {/* One live region announces the wait, then the decided record. */}
      <div role="status" className="sr-only">
        <Text as="p" font="main-ui-muted" color="text-04">
          {record !== null ? record : t("header.required", { headline })}
        </Text>
      </div>
      {record !== null ? (
        <div aria-hidden>
          <Content
            font="main-ui-muted"
            icon={
              status === "approved" || status === "approvedForSession"
                ? SvgCheckSquare
                : status === "rejected"
                  ? SvgX
                  : SvgClock
            }
            title={record}
          />
        </div>
      ) : (
        <CometEdge active tone="info" speedSeconds={3.6}>
          <div className="rounded-08 border border-status-info-03 overflow-hidden bg-background-neutral-00">
            <Collapsible.Root open={isOpen} onOpenChange={setIsOpen}>
              <Collapsible.Trigger className="flex w-full items-center gap-2 px-3 py-2 text-start transition-colors hover:bg-background-tint-02">
                <SvgLoader className="size-4 shrink-0 stroke-status-info-05 animate-spin" />
                <span className="min-w-0 flex-1">
                  <Text
                    font="main-ui-muted"
                    color="text-04"
                    wordWrap="wrap-anywhere"
                  >
                    {t("header.required", { headline })}
                  </Text>
                </span>
                {expiresAt && (
                  <Text
                    font="secondary-body"
                    color="text-03"
                    wordWrap="whitespace-nowrap"
                  >
                    {t("deadline", {
                      time: format.dateTime(new Date(expiresAt), {
                        hour: "numeric",
                        minute: "2-digit",
                      }),
                    })}
                  </Text>
                )}
                <SvgChevronDown
                  className={cn(
                    "size-4 shrink-0 stroke-text-03 transition-transform duration-150",
                    !isOpen && "-rotate-90"
                  )}
                />
              </Collapsible.Trigger>
              <Collapsible.Content>{details}</Collapsible.Content>
            </Collapsible.Root>
            <div className="px-3 pb-3 pt-1">
              <Section
                flexDirection="row"
                justifyContent="end"
                gap={1}
                wrap
                height="auto"
              >
                <Button
                  prominence="primary"
                  size="sm"
                  disabled={submitting}
                  onClick={() => void decide("approve_once")}
                  aria-label={t("approveOnce.ariaLabel")}
                >
                  {t("approveOnce.button")}
                </Button>
                {canApproveForSession && (
                  <Tooltip
                    tooltip={t("approveSession.tooltip")}
                    delayDuration={200}
                  >
                    <Button
                      prominence="secondary"
                      size="sm"
                      disabled={submitting}
                      onClick={() => void decide("approve_session")}
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
                  onClick={() => void decide("reject")}
                  aria-label={t("reject.ariaLabel")}
                >
                  {t("reject.button")}
                </Button>
              </Section>
            </div>
          </div>
        </CometEdge>
      )}
    </div>
  );
}
