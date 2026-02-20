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
        /* px-2 is the standard sidebar padding; pl-3.5 adds 1.5 to match Icon padding. */
        "flex p-2 pl-3.5 min-h-[3.25rem]",
        folded ? "justify-center" : "justify-between",
        applicationName ? "min-h-[3.75rem]" : "min-h-[3.25rem]"
      )}
    >
      {folded === undefined ? (
        logo()
      ) : folded ? (
        <>
          <div
            className={cn(
              "group-hover/SidebarWrapper:hidden",
              folded && "pt-1.5"
            )}
          >
            {logo()}
          </div>
          <div className="w-full justify-center hidden group-hover/SidebarWrapper:flex">
            {closeButton(false)}
          </div>
        </>
      ) : (
        <>
          <div className="pt-1.5">{logo()}</div>
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
