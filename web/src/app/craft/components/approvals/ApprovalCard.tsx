"use client";

import { useEffect, useRef, useState } from "react";
import { useSWRConfig } from "swr";

import { Button, Text } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgChevronDown, SvgLoader } from "@opal/icons";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import {
  ApprovalConflictError,
  postApprovalDecision,
} from "@/app/craft/services/apiServices";
import {
  ApprovalAction,
  ApprovalSubmitDecision,
  ApprovalView,
} from "@/app/craft/types/approvals";
import PayloadView from "@/app/craft/components/approvals/PayloadView";
import { SWR_KEYS } from "@/lib/swr-keys";

interface ApprovalCardProps {
  approval: ApprovalView;
  defaultOpen?: boolean;
}

// Single-action: name the action; multi-action: just count them. The
// per-action breakdown (with descriptions) is always shown in the body.
function approvalHeadline(approval: ApprovalView): string {
  if (approval.actions.length === 1) {
    return `${approval.actions[0]!.display_name} in ${approval.app_name}`;
  }
  return `${approval.actions.length} actions in ${approval.app_name}`;
}

function ActionList({ actions }: { actions: ApprovalAction[] }) {
  return (
    <div className="flex flex-col gap-2">
      {actions.map((action) => (
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
  );
}

/**
 * One row per pending approval. Approve/Reject sit in the header so the
 * user can decide without expanding; the body shows the per-action
 * breakdown (when multi) and the payload.
 */
export default function ApprovalCard({
  approval,
  defaultOpen = false,
}: ApprovalCardProps) {
  const { mutate } = useSWRConfig();
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(defaultOpen);

  // Guards setState after the post-decision SWR revalidation drops
  // this row from /live and the card unmounts mid-await.
  const mountedRef = useRef(true);
  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const headline = approvalHeadline(approval);
  const swrKey = SWR_KEYS.buildSessionLiveApprovals(approval.session_id);

  async function decide(decision: ApprovalSubmitDecision) {
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await postApprovalDecision(approval.approval_id, decision);
      void mutate(swrKey);
    } catch (e) {
      // 409 = already resolved (by someone else, or expired by the
      // proxy). Same UX as a successful submit: refetch and unmount.
      if (e instanceof ApprovalConflictError) {
        void mutate(swrKey);
        return;
      }
      if (mountedRef.current) {
        setErrorMessage(
          e instanceof Error ? e.message : "Failed to submit decision"
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
    <div className="rounded-08 border border-status-info-03 overflow-hidden bg-background-neutral-00">
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        {/*
         * Two triggers (header + chevron) because action buttons can't
         * nest inside a trigger (invalid HTML) and shouldn't toggle the
         * collapse. `data-approval-trigger` scopes the row's hover tint.
         */}
        <div
          className={cn(
            "flex items-center gap-1 pr-2 transition-colors",
            "has-[[data-approval-trigger]:hover]:bg-background-tint-02"
          )}
        >
          <CollapsibleTrigger asChild>
            <button
              data-approval-trigger
              className="flex items-center gap-2 min-w-0 flex-1 text-left px-3 py-2"
            >
              <SvgLoader className="size-4 shrink-0 stroke-status-info-05 animate-spin" />
              <Text font="main-ui-muted" color="text-04" nowrap>
                {headline}
              </Text>
            </button>
          </CollapsibleTrigger>
          <Button
            prominence="primary"
            size="sm"
            disabled={submitting}
            onClick={() => decide("APPROVED")}
          >
            Approve
          </Button>
          <Button
            prominence="secondary"
            size="sm"
            disabled={submitting}
            onClick={() => decide("REJECTED")}
          >
            Reject
          </Button>
          <CollapsibleTrigger asChild>
            <button
              data-approval-trigger
              aria-label={isOpen ? "Hide details" : "Show details"}
              className="p-1.5"
            >
              <SvgChevronDown
                className={cn(
                  "size-4 stroke-text-03 transition-transform duration-150",
                  !isOpen && "-rotate-90"
                )}
              />
            </button>
          </CollapsibleTrigger>
        </div>
        <CollapsibleContent>
          <div className="p-2 flex flex-col gap-3">
            <ActionList actions={approval.actions} />
            <PayloadView payload={approval.payload} />
            {errorMessage && (
              <div className="text-status-error-05">
                <Text font="secondary-body" color="inherit">
                  {errorMessage}
                </Text>
              </div>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
