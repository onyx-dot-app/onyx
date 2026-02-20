import React, { useCallback } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@opal/components";
import Logo from "@/refresh-components/Logo";
import { SvgSidebar } from "@opal/icons";

interface LogoSectionProps {
  folded?: boolean;
  onFoldClick?: () => void;
}

function LogoSection({ folded, onFoldClick }: LogoSectionProps) {
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
        "flex p-2 min-h-[3.25rem] gap-1",
        folded ? "justify-center" : "justify-between"
      )}
    >
      {folded === undefined ? (
        logo()
      ) : folded ? (
        <>
          <div className="group-hover/SidebarWrapper:hidden p-1 ">{logo()}</div>
          <div className="w-full justify-center hidden group-hover/SidebarWrapper:flex">
            {closeButton(false)}
          </div>
        </>
      ) : (
        <>
          {<div className="p-1.5 pb-0">{logo()}</div>}
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
