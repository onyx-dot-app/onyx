"use client";

import { SidebarLayouts } from "@opal/layouts";
import { SidebarLogoMark, SidebarWordmark } from "@/lib/app/components";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";

const SIDEBAR_LOGO_SIZE_PX = 28;

interface BrandedSidebarHeaderProps {
  /** Pinned content below the brand row, e.g. the sidebar's top tabs. */
  children?: React.ReactNode;
}

/**
 * The sidebar header with the workspace's branding: the logo mark, the
 * wordmark, and whether the folded sidebar keeps the logo. The app, admin and
 * Craft sidebars all render it, so their headers cannot drift apart.
 */
export default function BrandedSidebarHeader({
  children,
}: BrandedSidebarHeaderProps) {
  const showLogoWhenFolded = useShowLogoWhenFolded();
  return (
    <SidebarLayouts.Header
      logo={<SidebarLogoMark size={SIDEBAR_LOGO_SIZE_PX} />}
      wordmark={<SidebarWordmark size={SIDEBAR_LOGO_SIZE_PX} />}
      showLogoWhenFolded={showLogoWhenFolded}
    >
      {children}
    </SidebarLayouts.Header>
  );
}
