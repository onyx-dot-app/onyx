"use client";

import { useCallback } from "react";
import { Text, Button } from "@opal/components";
import { SvgArrowLeft, SvgSidebar } from "@opal/icons";
import { IllustrationContent } from "@opal/layouts";
import SvgNotFound from "@opal/illustrations/not-found";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { useProposal } from "@/app/proposal-review/hooks/useProposal";
import { useProposalReviewContext } from "@/app/proposal-review/contexts/ProposalReviewContext";
import useScreenSize from "@/hooks/useScreenSize";
import ProposalInfoPanel from "@/app/proposal-review/components/ProposalInfoPanel";
import ChecklistPanel from "@/app/proposal-review/components/ChecklistPanel";
import ReviewSidebar from "@/app/proposal-review/components/ReviewSidebar";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ProposalReviewProps {
  proposalId: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ProposalReview({ proposalId }: ProposalReviewProps) {
  const { proposal, isLoading, error, mutate } = useProposal(proposalId);
  const { leftSidebarFolded, setLeftSidebarFolded } =
    useProposalReviewContext();
  const { isMobile } = useScreenSize();

  const handleDecisionSubmitted = useCallback(() => {
    mutate();
  }, [mutate]);

  // --- Loading ---
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full w-full">
        <SimpleLoader className="h-8 w-8" />
      </div>
    );
  }

  // --- Error / not found ---
  if (error || !proposal) {
    return (
      <div className="flex flex-col items-center justify-center h-full w-full gap-4 p-8">
        <IllustrationContent
          illustration={SvgNotFound}
          title="Proposal not found"
          description="This proposal may have been removed or you may not have access."
        />
        <Button
          variant="default"
          prominence="secondary"
          href="/proposal-review"
        >
          Back to queue
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Top header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border-01 shrink-0">
        {/* Mobile sidebar toggle */}
        {isMobile && leftSidebarFolded && (
          <Button
            icon={SvgSidebar}
            onClick={() => setLeftSidebarFolded(false)}
            prominence="tertiary"
            size="sm"
          />
        )}
        <Button
          variant="default"
          prominence="tertiary"
          icon={SvgArrowLeft}
          size="sm"
          href="/proposal-review"
        />
        <Text font="main-ui-action" color="text-01">
          {proposal.metadata.title ?? "Untitled Proposal"}
        </Text>
        {proposal.metadata.jira_key && (
          <Text font="secondary-body" color="text-03">
            {proposal.metadata.jira_key}
          </Text>
        )}
      </div>

      {/* Three-panel layout */}
      <div className="flex flex-1 min-h-0">
        {/* Left panel: Proposal info */}
        <div className="w-[300px] shrink-0 border-r border-border-01 overflow-y-auto">
          <ProposalInfoPanel proposal={proposal} />
        </div>

        {/* Center panel: Checklist */}
        <div className="flex-1 min-w-0 overflow-hidden">
          <ChecklistPanel proposalId={proposalId} />
        </div>

        {/* Right panel: Review sidebar */}
        <div className="w-[320px] shrink-0 border-l border-border-01 overflow-y-auto">
          <ReviewSidebar
            proposalId={proposalId}
            onDecisionSubmitted={handleDecisionSubmitted}
          />
        </div>
      </div>
    </div>
  );
}
