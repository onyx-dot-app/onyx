"use client";

import { SidebarLayouts } from "@opal/layouts";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";
import { renderAppLogo } from "@/lib/app/utils";

export { renderAppLogo };

export interface SidebarWrapperProps {
  foldable?: boolean;
  children?: React.ReactNode;
}

/**
 * App-specific sidebar wrapper. Thin shell around `SidebarLayouts.Root`
 * that injects the enterprise-aware logo and show/hide rules.
 */
export default function SidebarWrapper({
  foldable = false,
  children,
}: SidebarWrapperProps) {
  const showLogoWhenFolded = useShowLogoWhenFolded();

  return (
    <SidebarLayouts.Root foldable={foldable}>
      <SidebarLayouts.Header
        logo={renderAppLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      />
      {children}
    </SidebarLayouts.Root>
  );
}
