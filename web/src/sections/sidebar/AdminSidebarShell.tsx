"use client";

import { ReactNode } from "react";
import { SidebarLayouts } from "@opal/layouts";
import { SidebarTab } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
import { renderSidebarLogo } from "@/lib/sidebar/utils";
import { useShowLogoWhenFolded } from "@/lib/sidebar/hooks";

interface BackTab {
  label: string;
  href: string;
  icon: IconFunctionComponent;
}

interface AdminSidebarShellProps {
  /**
   * Way back to the admin panel. Required: a sidebar that replaces the admin
   * nav must not strand the user.
   */
  back: BackTab;
  /** Unique key for scroll-position persistence, e.g. "create-connector". */
  scrollKey: string;
  children?: ReactNode;
}

/**
 * Chrome for an admin page that replaces `AdminSidebar` with its own sidebar.
 *
 * Owns the logo, the header and the fold controls, so a page supplies only the
 * body. Build every such sidebar on this, so none of them drifts from the
 * default one or comes out empty.
 */
export default function AdminSidebarShell({
  back,
  scrollKey,
  children,
}: AdminSidebarShellProps) {
  const showLogoWhenFolded = useShowLogoWhenFolded();

  return (
    <SidebarLayouts.Root>
      <SidebarLayouts.Header
        renderAppLogo={renderSidebarLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      >
        <SidebarTab icon={back.icon} href={back.href}>
          {back.label}
        </SidebarTab>
      </SidebarLayouts.Header>

      <SidebarLayouts.Body scrollKey={scrollKey}>
        {children}
      </SidebarLayouts.Body>
    </SidebarLayouts.Root>
  );
}
