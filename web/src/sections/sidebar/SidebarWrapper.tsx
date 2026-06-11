"use client";

import React from "react";
import { SidebarWrapper as OpalSidebarWrapper } from "@opal/layouts";
import { useSettingsContext } from "@/providers/SettingsProvider";
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
  folded?: boolean;
  onFoldClick?: () => void;
  children?: React.ReactNode;
}

/**
 * App-specific sidebar wrapper. Thin shell around the Opal `SidebarWrapper`
 * that injects the enterprise-aware logo and show/hide rules.
 */
export default function SidebarWrapper({
  folded,
  onFoldClick,
  children,
}: SidebarWrapperProps) {
  const settings = useSettingsContext();
  const showLogoWhenFolded =
    settings.enterpriseSettings?.logo_display_style !== "name_only";

  return (
    <OpalSidebarWrapper
      folded={folded}
      onFoldClick={onFoldClick}
      logo={renderAppLogo}
      showLogoWhenFolded={showLogoWhenFolded}
    >
      {children}
    </OpalSidebarWrapper>
  );
}
