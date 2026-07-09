"use client";

import { SidebarLayouts, useSidebarState } from "@opal/layouts";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";
import { useAppLogo } from "@/lib/app/hooks";

function SidebarLogo({ size = 28 }: { size?: number }) {
  const { folded } = useSidebarState();
  const Logo = useAppLogo(folded);
  return (
    <div className="px-1">
      <Logo size={size} />
    </div>
  );
}

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
        logo={SidebarLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      />
      {children}
    </SidebarLayouts.Root>
  );
}
