"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";

import { Button, Collapsible, Text, Tooltip } from "@opal/components";
import { Section } from "@opal/layouts";
import { cn, stripBidiControls } from "@opal/utils";
import { SvgChevronDown, SvgLoader } from "@opal/icons";
import CometEdge from "@/refresh-components/CometEdge";
import { RunStep } from "@/lib/timeline/components/RunStep";
import { STEP_ICONS } from "@/lib/timeline/icons";
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
  /**
   * What "approve for session" covers: a Craft session, a chat, or the rest of
   * a VM command, which submits "approve_command".
   */
  sessionScope?: "session" | "chat" | "command";
  canApproveForSession?: boolean;
  status: ApprovalStatus;
  /**
   * Submits a decision. A rejected promise shows an error next to the
   * details; the caller reports a decided request through `status`.
   */
  onDecide: (decision: ApprovalSubmitDecision) => Promise<void>;
}

/**
 * A pending request shows its details and decisions; a decided one, a
 * timeline step whose body holds the details.
 */
export default function ApprovalCard({
  actions: rawActions,
  appName: rawAppName,
  payload,
  expiresAt,
  sessionScope = "session",
  canApproveForSession = true,
  status,
  onDecide,
}: ApprovalCardProps) {
  const t = useTranslations("common.approvalCard");
  const format = useFormatter();
  const [isOpen, setIsOpen] = useState(true);
  const deadline = expiresAt
    ? t("deadline", {
        time: format.dateTime(new Date(expiresAt), {
          hour: "numeric",
          minute: "2-digit",
        }),
      })
    : null;
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

  // Integrations and tools choose these strings, so they show without bidi
  // controls; PayloadView strips the payload's.
  const actions = rawActions.map((item) => ({
    ...item,
    name: stripBidiControls(item.name),
    description:
      item.description === undefined
        ? undefined
        : stripBidiControls(item.description),
  }));
  const appName =
    rawAppName === undefined ? undefined : stripBidiControls(rawAppName);
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
  const scopeCopy = {
    session: {
      decision: "approve_session",
      button: "approveSession",
      record: "approvedForSession",
    },
    chat: {
      decision: "approve_session",
      button: "approveChat",
      record: "approvedForChat",
    },
    command: {
      decision: "approve_command",
      button: "approveCommand",
      record: "approvedForCommand",
    },
  } as const satisfies Record<
    NonNullable<ApprovalCardProps["sessionScope"]>,
    { decision: ApprovalSubmitDecision; button: string; record: string }
  >;
  const scope = scopeCopy[sessionScope];
  const sessionCopy = scope.button;
  // A decided request leaves a one-line record in the timeline.
  const record =
    status === "pending"
      ? null
      : t(`record.${status !== "approvedForSession" ? status : scope.record}`, {
          headline,
        });

  const single = actions.length === 1;

  const details = (
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
        <Text as="p" role="alert" font="secondary-body" color="status-error-05">
          {t("submitError")}
        </Text>
      )}
    </Section>
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
        <RunStep
          status="done"
          icon={STEP_ICONS.request}
          title={record}
          body={details}
        />
      ) : (
        <CometEdge active tone="info" speedSeconds={3.6}>
          <div className="rounded-08 border border-status-info-03 overflow-hidden bg-background-neutral-00">
            <Collapsible.Root open={isOpen} onOpenChange={setIsOpen}>
              {/* The spinner and the decisions show the wait; only screen
                  readers hear "Approval requested". */}
              <Collapsible.Trigger
                aria-label={[t("header.required", { headline }), deadline]
                  .filter(Boolean)
                  .join(". ")}
                className="flex w-full items-center gap-2 px-3 py-2 text-start transition-colors hover:bg-background-tint-02"
              >
                <SvgLoader className="size-4 shrink-0 stroke-status-info-05 motion-safe:animate-spin" />
                <span className="min-w-0 flex-1">
                  <Text
                    font="main-ui-muted"
                    color="text-04"
                    wordWrap="wrap-anywhere"
                  >
                    {headline}
                  </Text>
                </span>
                {deadline && (
                  <Text
                    font="secondary-body"
                    color="text-03"
                    wordWrap="whitespace-nowrap"
                  >
                    {deadline}
                  </Text>
                )}
                <SvgChevronDown
                  className={cn(
                    "size-4 shrink-0 stroke-text-03 transition-transform duration-150",
                    !isOpen && "-rotate-90"
                  )}
                />
              </Collapsible.Trigger>
              <Collapsible.Content>
                {/* Indented under the header text, past the spinner. */}
                <div className="ps-9 pe-3 pb-2">{details}</div>
              </Collapsible.Content>
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
                    tooltip={t(`${sessionCopy}.tooltip`)}
                    delayDuration={200}
                  >
                    <Button
                      prominence="secondary"
                      size="sm"
                      disabled={submitting}
                      onClick={() => void decide(scope.decision)}
                      aria-label={t(`${sessionCopy}.tooltip`)}
                    >
                      {t(`${sessionCopy}.button`)}
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
