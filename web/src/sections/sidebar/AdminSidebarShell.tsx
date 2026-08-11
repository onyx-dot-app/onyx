"use client";

import { ReactNode } from "react";
import { SidebarLayouts, useSidebarState } from "@opal/layouts";
import { Divider, SidebarTab } from "@opal/components";
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
  const { folded } = useSidebarState();

  return (
    <SidebarLayouts.Root>
      <SidebarLayouts.Header
        renderAppLogo={renderSidebarLogo}
        showLogoWhenFolded={showLogoWhenFolded}
      />

      <SidebarLayouts.Body scrollKey={scrollKey}>
        {children}
      </SidebarLayouts.Body>

      {/* The way out sits at the bottom, like "Exit Admin Panel" in `AdminSidebar`. */}
      <SidebarLayouts.Footer>
        {!folded && <Divider paddingPerpendicular="sm" />}
        <SidebarTab
          icon={back.icon}
          href={back.href}
          variant="sidebar-light"
          folded={folded}
        >
          {back.label}
        </SidebarTab>
      </SidebarLayouts.Footer>
    </SidebarLayouts.Root>
  );
}
