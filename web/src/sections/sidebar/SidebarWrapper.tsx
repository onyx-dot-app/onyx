import React, { useCallback } from "react";
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
  const applicationName = settings.enterpriseSettings?.application_name;
  const logoDisplayStyle = settings.enterpriseSettings?.logo_display_style;

  const logo = useCallback(
    (className?: string) => <Logo folded={folded} className={className} />,
    [folded]
  );
  const closeButton = useCallback(
    (shouldFold: boolean) => (
      <Button
        icon={SvgSidebar}
        prominence="tertiary"
        tooltip="Close Sidebar"
        onClick={onFoldClick}
      />
    ),
    [onFoldClick]
  );

  return (
    <div
      className={cn(
        /* px-2.5 => 2 for the standard sidebar padding + 0.5 for internal padding specific to this component. */
        "flex px-2.5 py-2",
        folded ? "justify-center" : "justify-between",
        applicationName
          ? "h-[3.75rem] min-h-[3.75rem]"
          : "h-[3.25rem] min-h-[3.25rem]"
      )}
    >
      {folded === undefined ? (
        <div className="p-1">{logo()}</div>
      ) : folded && logoDisplayStyle !== "name_only" ? (
        <>
          <div className="group-hover/SidebarWrapper:hidden pt-1.5">
            {logo()}
          </div>
          <div className="w-full justify-center hidden group-hover/SidebarWrapper:flex">
            {closeButton(false)}
          </div>
        </>
      ) : folded ? (
        <div className="flex w-full justify-center">{closeButton(false)}</div>
      ) : (
        <>
          <div className="p-1"> {logo()}</div>
          {closeButton(true)}
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
