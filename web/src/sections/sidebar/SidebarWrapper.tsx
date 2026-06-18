"use client";

import React from "react";
import { SidebarLayouts } from "@opal/layouts";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";
import Logo from "@/refresh-components/Logo";

/**
 * Renders the app-branded logo for use as the `logo` prop on sidebar primitives.
 * Exported so other sidebar entry points (e.g. AdminSidebar) can reuse it.
 */
export function renderAppLogo(folded: boolean | undefined): React.ReactNode {
  return (
    <div className="px-1">
      <Logo folded={folded} size={28} />
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
        logo={renderAppLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      />
      {children}
    </SidebarLayouts.Root>
  );
}
