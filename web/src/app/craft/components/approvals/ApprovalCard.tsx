"use client";

import { useEffect, useRef, useState } from "react";
import { useSWRConfig } from "swr";

import { Button, Text } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgChevronDown, SvgShield } from "@opal/icons";
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
}

/**
 * ApprovalCard - one row per pending approval. Mirrors CraftToolCard's
 * shape: shield icon + label + chevron in a hover-tinted header row,
 * with the structured payload preview and Approve/Reject buttons in the
 * expandable body. Reads as a sibling to the tool cards above.
 *
 * Defaults to open — the user explicitly needs the payload visible to
 * make a decision, not behind a click.
 */
export default function ApprovalCard({ approval }: ApprovalCardProps) {
  const { mutate } = useSWRConfig();
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(true);

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
    <div className="rounded-08 border border-status-warning-03 bg-status-warning-00">
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger asChild>
          <button className="w-full text-left rounded-md px-3 py-2 transition-colors hover:bg-background-tint-02">
            <div className="flex items-center gap-2 min-w-0 w-full">
              <SvgShield className="size-4 shrink-0 stroke-status-warning-05" />
              <Text font="main-ui-muted" color="text-04" nowrap>
                {label}
              </Text>
              <SvgChevronDown
                className={cn(
                  "size-4 stroke-text-03 transition-transform duration-150 shrink-0 ml-auto",
                  !isOpen && "-rotate-90"
                )}
              />
            </div>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-3 pb-3 pt-0 flex flex-col gap-3">
            <PayloadView
              actionType={approval.action_type}
              payload={approval.payload}
            />
            <div className="flex items-center gap-2">
              <Button
                prominence="primary"
                disabled={submitting}
                onClick={() => decide("APPROVED")}
              >
                Approve
              </Button>
              <Button
                prominence="secondary"
                disabled={submitting}
                onClick={() => decide("REJECTED")}
              >
                Reject
              </Button>
            </div>
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
