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
  ApprovalSubmitDecision,
  ApprovalView,
} from "@/app/craft/types/approvals";
import { resolveActionLabel } from "@/app/craft/components/approvals/actionLabels";
import PayloadView from "@/app/craft/components/approvals/PayloadView";
import { SWR_KEYS } from "@/lib/swr-keys";

interface ApprovalCardProps {
  approval: ApprovalView;
  defaultOpen?: boolean;
}

/**
 * ApprovalCard - one row per pending approval. Mirrors CraftToolCard's
 * shape: spinning loader + label + chevron in a hover-tinted header
 * row, with the structured payload preview in the expandable body.
 * Approve and Reject sit in the header so the user can decide without
 * expanding — the label alone is enough context for most low-stakes
 * actions, and the payload is one click away when verification is
 * needed.
 *
 * Visual treatment: status-info (blue) border on a transparent body.
 * Pairs with the SvgLoader spinner (also status-info) to read as
 * "agent is paused waiting on you" — distinct from the regular tool
 * cards (no border) but not alarming.
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

  const label = resolveActionLabel(approval.action_type);
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
      // Card usually unmounts on the next render once /live drops the
      // row, but if revalidation lags or the row stays visible we
      // still need to unstick the buttons.
      if (mountedRef.current) {
        setSubmitting(false);
      }
    }
  }

  return (
    <div className="rounded-08 border border-status-info-03 overflow-hidden">
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        {/*
         * Header row: shield+label is one trigger, chevron at the far
         * right is a second trigger (so the chevron sits in the
         * conventional position, after the action buttons). Action
         * buttons sit between as siblings — they can't live inside a
         * trigger (nested <button> is invalid HTML) and we don't want
         * clicking Approve to also toggle the collapse.
         *
         * Hover tint lives on the row container via `has-[...]:` so
         * it spans across the action buttons when the user hovers
         * either trigger. Hovering an action button doesn't match the
         * selector (no `data-approval-trigger` on those), so the row
         * goes clear and the button's own hover state takes over.
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
              className="flex items-center gap-2 min-w-0 flex-1 text-left px-3 py-1.5"
            >
              <SvgLoader className="size-4 shrink-0 stroke-status-info-05 animate-spin" />
              <Text font="main-ui-muted" color="text-04" nowrap>
                {label}
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
            <PayloadView
              actionType={approval.action_type}
              payload={approval.payload}
            />
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
