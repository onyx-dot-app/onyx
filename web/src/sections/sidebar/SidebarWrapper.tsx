import React, { useMemo } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@opal/components";
import Logo from "@/refresh-components/Logo";
import { SvgSidebar } from "@opal/icons";
import { useSettingsContext } from "@/providers/SettingsProvider";

interface LogoSectionProps {
  folded?: boolean;
  onFoldClick?: () => void;
}

function LogoSection({ folded, onFoldClick }: LogoSectionProps) {
  const settings = useSettingsContext();
  const logoDisplayStyle = settings.enterpriseSettings?.logo_display_style;

  const logo = useMemo(
    () => (
      <div className="px-1">
        <Logo folded={folded} size={28} />
      </div>
    ),
    [folded]
  );
  const closeButton = useMemo(
    () => (
      <div className="px-1">
        <Button
          icon={SvgSidebar}
          prominence="tertiary"
          tooltip="Close Sidebar"
          size="md"
          onClick={onFoldClick}
        />
      </div>
    ),
    [onFoldClick]
  );

  return (
    <div className="flex flex-row justify-between items-start pt-3 px-2">
      {folded === undefined ? (
        logo
      ) : folded && logoDisplayStyle !== "name_only" ? (
        <>
          <div className="group-hover/SidebarWrapper:hidden">{logo}</div>
          <div className="hidden group-hover/SidebarWrapper:flex">
            {closeButton}
          </div>
        </>
      ) : folded ? (
        closeButton
      ) : (
        <>
          {logo}
          {closeButton}
        </>
      )}
    </div>
  );
}

export interface SidebarWrapperProps {
  folded?: boolean;
  onFoldClick?: () => void;
  children?: React.ReactNode;
}

export default function SidebarWrapper({
  folded,
  onFoldClick,
  children,
}: SidebarWrapperProps) {
  return (
    // This extra `div` wrapping needs to be present (for some reason).
    // Without, the widths of the sidebars don't properly get set to the explicitly declared widths (i.e., `4rem` folded and `15rem` unfolded).
    <div>
      <div
        className={cn(
          "h-screen flex flex-col bg-background-tint-02 py-2 gap-4 group/SidebarWrapper transition-width duration-200 ease-in-out",
          folded ? "w-[3.25rem]" : "w-[15rem]"
        )}
      >
        <LogoSection folded={folded} onFoldClick={onFoldClick} />
        {children}
      </div>
    </div>
  );
}
