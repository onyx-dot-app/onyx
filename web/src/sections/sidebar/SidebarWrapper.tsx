import React, { Dispatch, SetStateAction } from "react";
import { cn } from "@/lib/utils";
import { OnyxIcon, OnyxLogoTypeIcon } from "@/components/icons/icons";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgSidebar from "@/icons/sidebar";

interface SidebarWrapperProps {
  folded?: boolean;
  setFolded?: Dispatch<SetStateAction<boolean>>;
  children: React.ReactNode;
}

export default function SidebarWrapper({
  folded,
  setFolded,
  children,
}: SidebarWrapperProps) {
  return (
    <div>
      <div
        className={cn(
          "h-full flex flex-col bg-background-tint-02 p-padding-button justify-between gap-padding-content group/SidebarWrapper",
          folded ? "w-[4rem]" : "w-[15rem]"
        )}
      >
        <div
          className={cn(
            "flex flex-row items-center px-spacing-interline py-spacing-inline flex-shrink-0",
            folded ? "justify-center" : "justify-between"
          )}
        >
          {folded ? (
            <div className="h-[2rem] flex flex-col justify-center items-center">
              <>
                <IconButton
                  icon={SvgSidebar}
                  tertiary
                  onClick={() => setFolded?.(false)}
                  className="hidden group-hover/SidebarWrapper:flex"
                />
                <OnyxIcon
                  size={24}
                  className="visible group-hover/SidebarWrapper:hidden"
                />
              </>
            </div>
          ) : (
            <>
              <OnyxLogoTypeIcon size={88} />
              <IconButton
                icon={SvgSidebar}
                tertiary
                onClick={() => setFolded?.(true)}
                className={cn(folded === undefined && "invisible")}
              />
            </>
          )}
        </div>

        {children}
      </div>
    </div>
  );
}
