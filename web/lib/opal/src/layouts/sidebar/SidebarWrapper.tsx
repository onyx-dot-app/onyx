"use client";

import React, { useMemo } from "react";
import { cn } from "@opal/utils";
import { Button } from "@opal/components";
import { SvgSidebar } from "@opal/icons";

export interface SidebarWrapperProps {
  folded?: boolean;
  onFoldClick?: () => void;
  /**
   * Render function for the logo/brand area at the top of the sidebar.
   * Receives the current fold state so the logo can adapt its appearance.
   */
  logo?: (folded: boolean | undefined) => React.ReactNode;
  /**
   * When `true` (default), the logo is shown in the folded state and swaps
   * with the close button on hover. When `false`, only the close button is
   * shown when folded (e.g. enterprise "name_only" logo display style).
   */
  showLogoWhenFolded?: boolean;
  children?: React.ReactNode;
}

export default function SidebarWrapper({
  folded,
  onFoldClick,
  logo,
  showLogoWhenFolded = true,
  children,
}: SidebarWrapperProps) {
  const closeButton = useMemo(
    () => (
      <div className="px-1">
        <Button
          icon={SvgSidebar}
          prominence="tertiary"
          tooltip={folded ? "Open Sidebar" : "Close Sidebar"}
          tooltipSide={folded ? "right" : "bottom"}
          size="md"
          onClick={onFoldClick}
        />
      </div>
    ),
    [folded, onFoldClick]
  );

  const logoEl = logo ? logo(folded) : null;

  return (
    // The outer wrapper establishes a plain block formatting context so that
    // `transition-[width]` on the inner div animates correctly. Without it the
    // inner div is a direct flex item of the page layout, and the flex
    // algorithm overrides the `width` property before the transition can fire,
    // so the sidebar snaps between widths instead of sliding.
    <div>
      <div
        className={cn(
          "h-screen flex flex-col bg-background-tint-02 py-2 gap-4 group/SidebarWrapper transition-width duration-200 ease-in-out",
          folded ? "w-(--sidebar-width-folded)" : "w-(--sidebar-width-expanded)"
        )}
      >
        <div className="flex flex-row justify-between items-start pt-3 px-2">
          {folded === undefined ? (
            logoEl
          ) : folded && showLogoWhenFolded && logoEl ? (
            <>
              <div className="group-hover/SidebarWrapper:hidden">{logoEl}</div>
              <div className="hidden group-hover/SidebarWrapper:flex">
                {closeButton}
              </div>
            </>
          ) : folded ? (
            closeButton
          ) : (
            <>
              {logoEl}
              {closeButton}
            </>
          )}
        </div>
        {children}
      </div>
    </div>
  );
}
