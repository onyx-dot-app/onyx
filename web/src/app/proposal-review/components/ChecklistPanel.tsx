"use client";

import { useEffect, useCallback, useState, useRef } from "react";
import { Button, Text } from "@opal/components";
import { SvgPlayCircle, SvgChevronDown, SvgChevronUp } from "@opal/icons";
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
import FindingCard from "@/app/proposal-review/components/FindingCard";
import { useFindings } from "@/app/proposal-review/hooks/useFindings";
import { useReviewStatus } from "@/app/proposal-review/hooks/useReviewStatus";
import { useProposalReviewContext } from "@/app/proposal-review/contexts/ProposalReviewContext";
import { triggerReview } from "@/app/proposal-review/services/apiServices";

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
    setCurrentReviewRunId,
    findingsLoaded,
    setFindingsLoaded,
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

  // Poll review status while running
  const { reviewStatus } = useReviewStatus(proposalId, isReviewRunning);

  // Fetch findings
  const {
    findingsByCategory,
    isLoading: findingsLoading,
    mutate: mutateFindings,
    findings,
  } = useFindings(proposalId);

  // When review completes, stop polling and load findings
  useEffect(() => {
    if (!reviewStatus) return;
    if (
      reviewStatus.status === "COMPLETED" ||
      reviewStatus.status === "FAILED"
    ) {
      setIsReviewRunning(false);
      if (reviewStatus.status === "COMPLETED") {
        setFindingsLoaded(true);
        mutateFindings();
      }
    }
  }, [reviewStatus, setIsReviewRunning, setFindingsLoaded, mutateFindings]);

  // On mount, if there are existing findings, mark as loaded
  useEffect(() => {
    if (findings.length > 0 && !findingsLoaded) {
      setFindingsLoaded(true);
    }
  }, [findings.length, findingsLoaded, setFindingsLoaded]);

  const handleRunReview = useCallback(async () => {
    if (!selectedRulesetId) return;

    setTriggerError(null);
    setIsReviewRunning(true);

    try {
      const result = await triggerReview(proposalId, selectedRulesetId);
      setCurrentReviewRunId(result.id);
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
  ]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Top bar: ruleset selector + run button */}
      <div className="flex items-center gap-3 p-4 border-b border-border-01 shrink-0">
        <div className="flex-1 max-w-[200px]">
          <RulesetSelector />
        </div>
        <Button
          variant="action"
          prominence="primary"
          icon={SvgPlayCircle}
          disabled={!selectedRulesetId || isReviewRunning}
          onClick={handleRunReview}
        >
          {isReviewRunning ? "Running..." : "Run Review"}
        </Button>
      </div>

      {triggerError && (
        <div className="px-4 pt-2">
          <Text font="secondary-body" color="text-03">
            {triggerError}
          </Text>
        </div>
      )}

      {/* Review progress */}
      {isReviewRunning && reviewStatus && (
        <ReviewProgress reviewStatus={reviewStatus} />
      )}

      {/* Loading spinner while review is starting */}
      {isReviewRunning && !reviewStatus && (
        <div className="flex items-center justify-center py-8">
          <SimpleLoader className="h-6 w-6" />
        </div>
      )}

      {/* Findings list */}
      <div className="flex-1 overflow-y-auto">
        {!isReviewRunning && findingsLoading && (
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

        {!isReviewRunning && findingsByCategory.length > 0 && (
          <div className="flex flex-col gap-3 p-4">
            {findingsByCategory.map((group) => (
              <CategoryGroup
                key={group.category}
                category={group.category}
                findings={group.findings}
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
  findings: import("@/app/proposal-review/types").Finding[];
  onDecisionSaved: () => void;
}

function CategoryGroup({
  category,
  findings,
  onDecisionSaved,
}: CategoryGroupProps) {
  const failCount = findings.filter(
    (f) => f.verdict === "FAIL" || f.verdict === "FLAG"
  ).length;
  const passCount = findings.filter((f) => f.verdict === "PASS").length;
  const decidedCount = findings.filter((f) => f.decision !== null).length;

  // Default open if there are failures/flags
  const [isOpen, setIsOpen] = useState(failCount > 0);

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
              onDecisionSaved={onDecisionSaved}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
