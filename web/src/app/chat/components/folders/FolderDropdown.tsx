import React, { useState, ReactNode, forwardRef } from "react";
import { Folder } from "./interfaces";
import { ChatSession } from "@/app/chat/interfaces";
import { Caret } from "@/components/icons/icons";
import { cn } from "@/lib/utils";

interface FolderDropdownProps {
  folder: Folder;
  currentChatId?: string;
  showShareModal?: (chatSession: ChatSession) => void;
  closeSidebar?: () => void;
  children?: ReactNode;
  index: number;
}

export const FolderDropdown = forwardRef<HTMLDivElement, FolderDropdownProps>(
  ({ folder, children, index }: FolderDropdownProps, ref) => {
    const [isOpen, setIsOpen] = useState(true);

    return (
      <div className="overflow-visible pt-2 w-full">
        <div
          className="sticky top-0 bg-background-sidebar dark:bg-transparent z-10"
          style={{ zIndex: 1000 - index }}
        >
          <div
            ref={ref}
            className={cn(
              "flex",
              "overflow-visible",
              "items-center",
              "w-full",
              "text-text-darker",
              "rounded-md",
              "p-1",
              "bg-background-sidebar",
              "dark:bg-[#000]",
              "sticky",
              "top-0"
            )}
            style={{ zIndex: 10 - index }}
          >
            <button
              className="flex overflow-hidden bg-background-sidebar dark:bg-[#000] items-center flex-grow"
              onClick={() => setIsOpen(!isOpen)}
            >
              {isOpen ? (
                <Caret size={16} className="mr-1" />
              ) : (
                <Caret size={16} className="-rotate-90 mr-1" />
              )}
              <div className="flex items-center">
                <span className="text-sm font-[500]">{folder.folder_name}</span>
              </div>
            </button>
          </div>
          {isOpen && (
            <div className="overflow-visible mr-3 ml-1 mt-1">{children}</div>
          )}
        </div>
      </div>
    );
  }
);

FolderDropdown.displayName = "FolderDropdown";
