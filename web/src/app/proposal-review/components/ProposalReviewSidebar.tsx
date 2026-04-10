"use client";

import { memo, useMemo } from "react";
import { usePathname } from "next/navigation";
import { SvgArrowLeft, SvgCheckSquare, SvgSettings } from "@opal/icons";
import { SidebarTab } from "@opal/components";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";
import SidebarBody from "@/sections/sidebar/SidebarBody";
import AccountPopover from "@/sections/sidebar/AccountPopover";
import { cn } from "@/lib/utils";
import useScreenSize from "@/hooks/useScreenSize";
import { useProposalReviewContext } from "@/app/proposal-review/contexts/ProposalReviewContext";

// ============================================================================
// Sidebar Inner
// ============================================================================

interface ProposalReviewSidebarInnerProps {
  folded: boolean;
  onFoldClick: () => void;
}

const MemoizedSidebarInner = memo(function ProposalReviewSidebarInner({
  folded,
  onFoldClick,
}: ProposalReviewSidebarInnerProps) {
  const pathname = usePathname();

  // Highlight "Proposals" for both the queue and any proposal detail pages
  const isProposalsActive =
    pathname === "/proposal-review" ||
    pathname.startsWith("/proposal-review/proposals");

  const queueButton = useMemo(
    () => (
      <SidebarTab
        icon={SvgCheckSquare}
        folded={folded}
        href="/proposal-review"
        selected={isProposalsActive}
      >
        Proposals
      </SidebarTab>
    ),
    [folded, isProposalsActive]
  );

  const adminButton = useMemo(
    () => (
      <SidebarTab
        icon={SvgSettings}
        folded={folded}
        href="/admin/proposal-review"
        selected={pathname.startsWith("/admin/proposal-review")}
      >
        Settings
      </SidebarTab>
    ),
    [folded, pathname]
  );

  const backButton = useMemo(
    () => (
      <SidebarTab icon={SvgArrowLeft} folded={folded} href="/app">
        Back to Onyx
      </SidebarTab>
    ),
    [folded]
  );

  const footer = useMemo(
    () => (
      <div>
        {adminButton}
        {backButton}
        <AccountPopover folded={folded} />
      </div>
    ),
    [folded, adminButton, backButton]
  );

  return (
    <SidebarWrapper folded={folded} onFoldClick={onFoldClick}>
      <SidebarBody
        pinnedContent={
          <div className="flex flex-col gap-0.5">{queueButton}</div>
        }
        footer={footer}
        scrollKey="proposal-review-sidebar"
      />
    </SidebarWrapper>
  );
});

// ============================================================================
// Sidebar (Main Export)
// ============================================================================

export default function ProposalReviewSidebar() {
  const { leftSidebarFolded, setLeftSidebarFolded } =
    useProposalReviewContext();
  const { isMobile } = useScreenSize();

  if (!isMobile) {
    return (
      <MemoizedSidebarInner
        folded={leftSidebarFolded}
        onFoldClick={() => setLeftSidebarFolded((prev) => !prev)}
      />
    );
  }

  return (
    <>
      <div
        className={cn(
          "fixed inset-y-0 left-0 z-50 transition-transform duration-200",
          leftSidebarFolded ? "-translate-x-full" : "translate-x-0"
        )}
      >
        <MemoizedSidebarInner
          folded={false}
          onFoldClick={() => setLeftSidebarFolded(true)}
        />
      </div>

      {/* Backdrop to close sidebar on mobile */}
      <div
        className={cn(
          "fixed inset-0 z-40 bg-mask-03 backdrop-blur-03 transition-opacity duration-200",
          leftSidebarFolded
            ? "opacity-0 pointer-events-none"
            : "opacity-100 pointer-events-auto"
        )}
        onClick={() => setLeftSidebarFolded(true)}
      />
    </>
  );
}
