"use client";

import { memo } from "react";
import { usePathname } from "next/navigation";
import { SvgArrowLeft, SvgCheckSquare, SvgSettings } from "@opal/icons";
import { SidebarTab } from "@opal/components";
import * as SidebarLayouts from "@/layouts/sidebar-layouts";
import { useSidebarState, useSidebarFolded } from "@/layouts/sidebar-layouts";
import AccountPopover from "@/sections/sidebar/AccountPopover";

// ============================================================================
// Sidebar Content
// ============================================================================

const MemoizedSidebarContent = memo(function ProposalReviewSidebarContent() {
  const pathname = usePathname();
  const folded = useSidebarFolded();

  const isProposalsActive =
    pathname === "/proposal-review" ||
    pathname.startsWith("/proposal-review/proposals");

  return (
    <>
      <SidebarLayouts.Body scrollKey="proposal-review-sidebar">
        <div className="flex flex-col gap-0.5">
          <SidebarTab
            icon={SvgCheckSquare}
            folded={folded}
            href="/proposal-review"
            selected={isProposalsActive}
          >
            Proposals
          </SidebarTab>
        </div>
      </SidebarLayouts.Body>
      <SidebarLayouts.Footer>
        <SidebarTab
          icon={SvgSettings}
          folded={folded}
          href="/admin/proposal-review"
          selected={pathname.startsWith("/admin/proposal-review")}
        >
          Settings
        </SidebarTab>
        <SidebarTab icon={SvgArrowLeft} folded={folded} href="/app">
          Back to Onyx
        </SidebarTab>
        <AccountPopover folded={folded} />
      </SidebarLayouts.Footer>
    </>
  );
});

// ============================================================================
// Sidebar (Main Export)
// ============================================================================

export default function ProposalReviewSidebar() {
  const { folded, setFolded } = useSidebarState();

  return (
    <SidebarLayouts.Root folded={folded} onFoldChange={setFolded} foldable>
      <MemoizedSidebarContent />
    </SidebarLayouts.Root>
  );
}
