import React, { useCallback } from "react";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import Logo from "@/refresh-components/Logo";
import { SvgSidebar } from "@opal/icons";
import { useSettingsContext } from "@/components/settings/SettingsProvider";

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
      <IconButton
        icon={SvgSidebar}
        tertiary
        tooltip="Close Sidebar"
        onClick={onFoldClick}
      />
    ),
    [onFoldClick]
  );

  return (
    <div
      className={cn(
        // # Note
        //
        // The `px-3.5` was chosen carefully to make the logo sit in the center of the folded + unfolded sidebar view.
        // If you want to modify it, you'll also have to modify the size of the sidebar (located at the bottom of this file, annotated with `@HERE`).
        //
        // - @raunakab
        "flex flex-row items-center py-1 gap-1 min-h-[3.5rem] px-3.5",
        folded ? "justify-start" : "justify-between"
      )}
    >
      {folded === undefined ? (
        logo()
      ) : folded ? (
        <>
          <div className="group-hover/SidebarWrapper:hidden">{logo()}</div>
          <div className="w-full justify-center hidden group-hover/SidebarWrapper:flex">
            {closeButton(false)}
          </div>
        </>
      ) : (
        <>
          {logo()}
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

          // @HERE (size of sidebar)
          //
          // - @raunakab
          folded ? "w-[3.25rem]" : "w-[15rem]"
        )}
      >
        <LogoSection folded={folded} onFoldClick={onFoldClick} />
        {children}
      </div>
    </div>
  );
}
