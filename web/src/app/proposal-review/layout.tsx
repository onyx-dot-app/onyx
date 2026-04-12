"use client";

import { ProposalReviewProvider } from "@/app/proposal-review/contexts/ProposalReviewContext";
import ProposalReviewSidebar from "@/app/proposal-review/components/ProposalReviewSidebar";

/**
 * Proposal Review Layout
 *
 * Follows the Craft pattern: custom sidebar on the left, content on the right.
 * The root AppProvider already includes SidebarStateProvider, so the sidebar
 * shares fold state with the main app automatically.
 */
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <ProposalReviewProvider>
      <div className="flex flex-row w-full h-full">
        <ProposalReviewSidebar />
        <div className="relative flex-1 h-full overflow-hidden">{children}</div>
      </div>
    </ProposalReviewProvider>
  );
}
