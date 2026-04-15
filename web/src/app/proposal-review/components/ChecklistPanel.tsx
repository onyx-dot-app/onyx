"use client";

import { useEffect, useCallback, useState, useRef } from "react";
import { Button, Text } from "@opal/components";
import {
  SvgPlayCircle,
  SvgRefreshCw,
  SvgChevronDown,
  SvgChevronUp,
} from "@opal/icons";
import { IllustrationContent } from "@opal/layouts";
import SvgEmpty from "@opal/illustrations/empty";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/refresh-components/Collapsible";
import RulesetSelector from "@/app/proposal-review/components/RulesetSelector";
import ReviewProgress from "@/app/proposal-review/components/ReviewProgress";
import RunHistorySelector from "@/app/proposal-review/components/RunHistorySelector";
import FindingCard from "@/app/proposal-review/components/FindingCard";
import { useFindings } from "@/app/proposal-review/hooks/useFindings";
import { useReviewStatus } from "@/app/proposal-review/hooks/useReviewStatus";
import { useReviewRuns } from "@/app/proposal-review/hooks/useReviewRuns";
import { useProposalReviewContext } from "@/app/proposal-review/contexts/ProposalReviewContext";
import {
  triggerReview,
  retryFailedRules,
} from "@/app/proposal-review/services/apiServices";
import type { Finding } from "@/app/proposal-review/types";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ChecklistPanelProps {
  proposalId: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ChecklistPanel({ proposalId }: ChecklistPanelProps) {
  const {
    selectedRulesetId,
    isReviewRunning,
    setIsReviewRunning,
    currentReviewRunId,
    setCurrentReviewRunId,
    viewingRunId,
    setViewingRunId,
    focusedFindingId,
    setFocusedFindingId,
    resetReviewState,
  } = useProposalReviewContext();

  const [triggerError, setTriggerError] = useState<string | null>(null);

  // Reset review state when navigating to a different proposal
  const prevProposalIdRef = useRef(proposalId);
  useEffect(() => {
    if (prevProposalIdRef.current !== proposalId) {
      prevProposalIdRef.current = proposalId;
      resetReviewState();
      setTriggerError(null);
    }
  }, [proposalId, resetReviewState]);

  // Always fetch latest review run; poll while running
  const { reviewStatus, mutate: mutateReviewStatus } = useReviewStatus(
    proposalId,
    isReviewRunning
  );

  // Fetch all runs for the history selector
  const { runs: reviewRuns, mutate: mutateReviewRuns } =
    useReviewRuns(proposalId);

  const isViewingLatest =
    viewingRunId === null || viewingRunId === reviewRuns[0]?.id;

  // Fetch findings — poll while review is running so results appear in real time.
  // When viewing an older run, don't poll.
  const {
    findingsByCategory,
    isLoading: findingsLoading,
    mutate: mutateFindings,
    findings,
  } = useFindings(
    proposalId,
    isViewingLatest && isReviewRunning,
    isViewingLatest ? null : viewingRunId
  );

  // When review completes, stop polling and load findings.
  // Guards: (1) must be actively polling, (2) must have status data,
  // (3) must match the run we triggered — prevents stale COMPLETED status
  // from a previous run from immediately killing polling on re-run.
  useEffect(() => {
    if (!isReviewRunning || !reviewStatus || !currentReviewRunId) return;
    if (reviewStatus.id !== currentReviewRunId) return;
    if (
      reviewStatus.status === "COMPLETED" ||
      reviewStatus.status === "FAILED"
    ) {
      setIsReviewRunning(false);
      mutateFindings();
      mutateReviewRuns();
    }
  }, [
    reviewStatus,
    isReviewRunning,
    currentReviewRunId,
    setIsReviewRunning,
    mutateFindings,
    mutateReviewRuns,
  ]);

  const handleRunReview = useCallback(async () => {
    if (!selectedRulesetId) return;

    setTriggerError(null);
    // Clear run ID first — blocks the completion effect and hides stale
    // data via isTriggerInFlight until the trigger API returns.
    setCurrentReviewRunId(null);
    setIsReviewRunning(true);
    setViewingRunId(null);

    try {
      const result = await triggerReview(proposalId, selectedRulesetId);
      setCurrentReviewRunId(result.id);
      // Revalidate caches — the backend APIs now return data for the new
      // (latest) run, so SWR naturally picks up fresh data.
      mutateReviewStatus();
      mutateFindings();
      mutateReviewRuns();
    } catch (err) {
      setIsReviewRunning(false);
      setTriggerError(
        err instanceof Error ? err.message : "Failed to start review"
      );
    }
  }, [
    proposalId,
    selectedRulesetId,
    setIsReviewRunning,
    setCurrentReviewRunId,
    mutateFindings,
    mutateReviewStatus,
    mutateReviewRuns,
  ]);

  const handleRetryFailed = useCallback(async () => {
    setTriggerError(null);
    setCurrentReviewRunId(null);
    setIsReviewRunning(true);
    setViewingRunId(null);

    try {
      const result = await retryFailedRules(proposalId);
      setCurrentReviewRunId(result.id);
      mutateReviewStatus();
    } catch (err) {
      setIsReviewRunning(false);
      setTriggerError(err instanceof Error ? err.message : "Failed to retry");
    }
  }, [
    proposalId,
    setIsReviewRunning,
    setCurrentReviewRunId,
    mutateReviewStatus,
  ]);

  // True between clicking "Run Review" and the trigger API returning.
  // During this window, currentReviewRunId is null — we hide stale data
  // from the previous run so the UI looks clean.
  const isTriggerInFlight = isReviewRunning && !currentReviewRunId;

  const showRetryButton =
    isViewingLatest &&
    !isReviewRunning &&
    (reviewStatus?.status === "COMPLETED" ||
      reviewStatus?.status === "FAILED") &&
    (reviewStatus?.failed_rules ?? 0) > 0;

  const handleFocusHandled = useCallback(
    () => setFocusedFindingId(null),
    [setFocusedFindingId]
  );

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Top bar: ruleset selector + run button + progress */}
      <div className="flex items-center gap-3 p-4 border-b border-border-01 shrink-0">
        <div className="shrink-0 max-w-[200px]">
          <RulesetSelector />
        </div>
        <Button
          variant="default"
          prominence="primary"
          icon={SvgPlayCircle}
          disabled={!selectedRulesetId || isReviewRunning}
          onClick={handleRunReview}
        >
          {isReviewRunning ? "Running..." : "Run Review"}
        </Button>
        {reviewStatus && !isTriggerInFlight && (
          <ReviewProgress reviewStatus={reviewStatus} />
        )}
        {showRetryButton && (
          <Button
            variant="default"
            prominence="secondary"
            icon={SvgRefreshCw}
            size="sm"
            onClick={handleRetryFailed}
          >
            Retry Failed
          </Button>
        )}
        {isReviewRunning && !reviewStatus && (
          <SimpleLoader className="h-4 w-4" />
        )}
      </div>

      {triggerError && (
        <div className="px-4 pt-2">
          <Text font="secondary-body" color="text-03">
            {triggerError}
          </Text>
        </div>
      )}

      {/* Run history selector */}
      {reviewRuns.length > 1 && (
        <RunHistorySelector
          runs={reviewRuns}
          selectedRunId={viewingRunId}
          onSelectRun={setViewingRunId}
        />
      )}

      {/* Findings list */}
      <div className="flex-1 overflow-y-auto">
        {(isTriggerInFlight || (!isReviewRunning && findingsLoading)) && (
          <div className="flex items-center justify-center py-8">
            <SimpleLoader className="h-6 w-6" />
          </div>
        )}

        {!isReviewRunning && !findingsLoading && findings.length === 0 && (
          <div className="flex items-center justify-center py-12 px-4">
            <IllustrationContent
              illustration={SvgEmpty}
              title="No review results"
              description="Select a ruleset and click Run Review to evaluate this proposal."
            />
          </div>
        )}

        {!isTriggerInFlight && findingsByCategory.length > 0 && (
          <div className="flex flex-col gap-3 p-4">
            {findingsByCategory.map((group) => (
              <CategoryGroup
                key={group.category}
                category={group.category}
                findings={group.findings}
                focusedFindingId={focusedFindingId}
                onFocusHandled={handleFocusHandled}
                onDecisionSaved={() => mutateFindings()}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CategoryGroup: collapsible group of findings
// ---------------------------------------------------------------------------

interface CategoryGroupProps {
  category: string;
  findings: Finding[];
  focusedFindingId: string | null;
  onFocusHandled: () => void;
  onDecisionSaved: () => void;
}

function CategoryGroup({
  category,
  findings,
  focusedFindingId,
  onFocusHandled,
  onDecisionSaved,
}: CategoryGroupProps) {
  const failCount = findings.filter(
    (f) => f.verdict === "FAIL" || f.verdict === "FLAG"
  ).length;
  const decidedCount = findings.filter(
    (f) => f.decision_action !== null
  ).length;

  // Default open if there are failures/flags
  const [isOpen, setIsOpen] = useState(failCount > 0);

  // Auto-open this group when a finding inside it is focused
  const containsFocused =
    focusedFindingId !== null &&
    findings.some((f) => f.id === focusedFindingId);

  useEffect(() => {
    if (containsFocused) {
      setIsOpen(true);
    }
  }, [containsFocused]);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <div
          role="button"
          tabIndex={0}
          className="flex items-center justify-between w-full py-2 px-3 rounded-08 hover:bg-background-neutral-02 cursor-pointer"
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setIsOpen((prev) => !prev);
            }
          }}
        >
          <div className="flex items-center gap-2">
            {isOpen ? (
              <SvgChevronUp className="h-4 w-4 text-text-03" />
            ) : (
              <SvgChevronDown className="h-4 w-4 text-text-03" />
            )}
            <Text font="main-ui-action" color="text-04">
              {category}
            </Text>
          </div>
          <div className="flex items-center gap-3">
            {failCount > 0 && (
              <Text font="secondary-body" color="text-03">
                {`${failCount} issue${failCount !== 1 ? "s" : ""}`}
              </Text>
            )}
            <Text font="secondary-body" color="text-03">
              {`${decidedCount}/${findings.length} reviewed`}
            </Text>
          </div>
        </div>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="flex flex-col gap-2 pt-2 pl-6">
          {findings.map((finding) => (
            <FindingCard
              key={finding.id}
              finding={finding}
              isFocused={finding.id === focusedFindingId}
              onFocusHandled={onFocusHandled}
              onDecisionSaved={onDecisionSaved}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
