"use client";

import { memo, useMemo, useCallback } from "react";
import { useBuildContext } from "@/app/build/contexts/BuildContext";
import { useBuildSession } from "@/app/build/hooks/useBuildSession";
import { useUsageLimits } from "@/app/build/hooks/useUsageLimits";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import Text from "@/refresh-components/texts/Text";
import SidebarWrapper from "@/sections/sidebar/SidebarWrapper";
import SidebarBody from "@/sections/sidebar/SidebarBody";
import SidebarSection from "@/sections/sidebar/SidebarSection";
import { SvgEditBig, SvgArrowLeft } from "@opal/icons";

// ============================================================================
// Build Sidebar Inner
// ============================================================================

interface BuildSidebarInnerProps {
  folded: boolean;
  onFoldClick: () => void;
}

const MemoizedBuildSidebarInner = memo(
  ({ folded, onFoldClick }: BuildSidebarInnerProps) => {
    const { hasSession, resetSession, sessionHistory } = useBuildSession();
    const { limits, isEnabled } = useUsageLimits();

    // Build section title with usage if cloud is enabled
    const sessionsTitle = useMemo(() => {
      if (isEnabled && limits) {
        return `Sessions (${limits.messagesUsed}/${limits.limit})`;
      }
      return "Sessions";
    }, [isEnabled, limits]);

    const handleNewBuild = useCallback(() => {
      resetSession();
    }, [resetSession]);

    const newBuildButton = useMemo(
      () => (
        <SidebarTab
          leftIcon={SvgEditBig}
          folded={folded}
          onClick={handleNewBuild}
          transient={!hasSession}
        >
          New Build
        </SidebarTab>
      ),
      [folded, handleNewBuild, hasSession]
    );

    const backToChatButton = useMemo(
      () => (
        <SidebarTab leftIcon={SvgArrowLeft} folded={folded} href="/chat">
          Back to Chat
        </SidebarTab>
      ),
      [folded]
    );

    return (
      <SidebarWrapper folded={folded} onFoldClick={onFoldClick}>
        <SidebarBody
          actionButtons={newBuildButton}
          footer={backToChatButton}
          scrollKey="build-sidebar"
        >
          {!folded && (
            <SidebarSection title={sessionsTitle}>
              {/* Placeholder for build session history */}
              <div className="px-3 py-2">
                <Text as="p" text01 secondaryBody>
                  Your build sessions will appear here.
                </Text>
              </div>
            </SidebarSection>
          )}
        </SidebarBody>
      </SidebarWrapper>
    );
  }
);

MemoizedBuildSidebarInner.displayName = "BuildSidebarInner";

// ============================================================================
// Build Sidebar (Main Export)
// ============================================================================

export default function BuildSidebar() {
  const { leftSidebarFolded, setLeftSidebarFolded } = useBuildContext();

  return (
    <MemoizedBuildSidebarInner
      folded={leftSidebarFolded}
      onFoldClick={() => setLeftSidebarFolded((prev) => !prev)}
    />
  );
}
