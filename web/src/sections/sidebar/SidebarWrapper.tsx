import React, { Dispatch, SetStateAction, useCallback } from "react";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgSidebar from "@/icons/sidebar";
import Logo from "@/refresh-components/Logo";

interface LogoSectionProps {
  folded?: boolean;
  setFolded?: Dispatch<SetStateAction<boolean>>;
}

function LogoSection({ folded, setFolded }: LogoSectionProps) {
  const logo = useCallback(
    (className?: string) => <Logo folded={folded} className={className} />,
    [folded]
  );

  return (
    <div
      className={cn(
        "flex flex-row items-center px-spacing-paragraph py-spacing-inline flex-shrink-0 gap-spacing-paragraph",
        folded ? "justify-center" : "justify-between"
      )}
    >
      {folded === undefined ? (
        logo()
      ) : folded ? (
        <div className="h-[2rem] flex flex-col justify-center items-center">
          {logo("visible group-hover/SidebarWrapper:hidden")}
          <IconButton
            icon={SvgSidebar}
            tertiary
            tooltip="Close Sidebar"
            onClick={() => setFolded?.(false)}
            className="hidden group-hover/SidebarWrapper:flex"
          />
        </div>
      ) : (
        <>
          {logo()}
          <IconButton
            icon={SvgSidebar}
            tertiary
            tooltip="Close Sidebar"
            onClick={() => setFolded?.(true)}
          />
        </>
      )}
    </div>
  );
}

export interface SidebarWrapperProps {
  folded?: boolean;
  setFolded?: Dispatch<SetStateAction<boolean>>;
  children?: React.ReactNode;
}

export default function SidebarWrapper({
  folded,
  setFolded,
  children,
}: SidebarWrapperProps) {
  return (
    // This extra `div` wrapping needs to be present (for some reason).
    // Without, the widths of the sidebars don't properly get set to the explicitly declared widths (i.e., `4rem` folded and `15rem` unfolded).
    <div>
      <div
        className={cn(
          "h-screen flex flex-col bg-background-tint-02 py-spacing-interline gap-spacing-paragraph group/SidebarWrapper",
          folded ? "w-[3.5rem]" : "w-[15rem]"
        )}
      >
        <LogoSection folded={folded} setFolded={setFolded} />
        {children}
      </div>
    </div>
  );
}
