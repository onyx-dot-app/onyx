"use client";

import { SvgShield, SvgSidebar } from "@opal/icons";
import { Content } from "@opal/layouts";
import { Button } from "@opal/components";
import ProposalQueue from "@/app/proposal-review/components/ProposalQueue";
import { useProposalReviewContext } from "@/app/proposal-review/contexts/ProposalReviewContext";
import useScreenSize from "@/hooks/useScreenSize";

/**
 * Proposal Review Queue Page
 *
 * Main landing page for officers. Shows a filterable, sortable table
 * of proposals imported from Jira.
 */
export default function ProposalReviewPage() {
  const { leftSidebarFolded, setLeftSidebarFolded } =
    useProposalReviewContext();
  const { isMobile } = useScreenSize();

  return (
    <div className="flex flex-col h-full w-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-border-01 shrink-0">
        {/* Mobile sidebar toggle */}
        {isMobile && leftSidebarFolded && (
          <Button
            icon={SvgSidebar}
            onClick={() => setLeftSidebarFolded(false)}
            prominence="tertiary"
            size="sm"
          />
        )}
        <Content
          sizePreset="section"
          variant="heading"
          icon={SvgShield}
          title="Proposal Review"
          description="Review and evaluate grant proposals"
        />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <ProposalQueue />
      </div>
    </div>
  );
}
