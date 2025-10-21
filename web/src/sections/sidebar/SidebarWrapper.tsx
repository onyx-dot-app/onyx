import React, { Dispatch, SetStateAction, useMemo } from "react";
import { cn } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgSidebar from "@/icons/sidebar";
import Logo from "@/refresh-components/Logo";

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
  const logo = useMemo(
    () => (
      <Logo
        folded={folded}
        className={cn(folded && "visible group-hover/SidebarWrapper:hidden")}
      />
    ),
    [folded]
  );

  return (
    // This extra `div` wrapping needs to be present (for some reason).
    // Without, the widths of the sidebars don't properly get set to the explicitly declared widths (i.e., `4rem` folded and `15rem` unfolded).
    <div>
      <div
        className={cn(
          "h-screen",
          "flex flex-col",
          "py-spacing-interline",
          "bg-background-tint-02",
          "justify-between",
          "group/SidebarWrapper",
          folded ? "w-[4rem]" : "w-[15rem]"
        )}
      >
        <div
          className={cn(
            "flex",
            "flex-row",
            "items-center",
            "px-spacing-paragraph",
            "pt-spacing-interline-mini",
            "pb-spacing-paragraph",
            "flex-shrink-0",
            folded ? "justify-center" : "justify-between"
          )}
        >
          {folded ? (
            <div className="h-[2rem] flex flex-col justify-center items-center">
              <>
                {logo}
                <IconButton
                  icon={SvgSidebar}
                  tertiary
                  onClick={() => setFolded?.(false)}
                  className="hidden group-hover/SidebarWrapper:flex"
                  tooltip="Close Sidebar"
                />
              </>
            </div>
          ) : (
            <>
              {logo}
              <IconButton
                icon={SvgSidebar}
                tertiary
                onClick={() => setFolded?.(true)}
                className={cn(folded === undefined && "invisible")}
                tooltip="Close Sidebar"
              />
            </>
          )}
        </div>

        {children}
      </div>
    </div>
  );
}
