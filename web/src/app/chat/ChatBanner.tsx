"use client";

import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useContext, useState, useRef, useLayoutEffect } from "react";
import { Popover } from "@/components/popover/Popover";
import { ChevronDownIcon } from "@/components/icons/icons";
import { MinimalMarkdown } from "@/components/chat_search/MinimalMarkdown";

export function ChatBanner() {
  const settings = useContext(SettingsContext);
  const [isOverflowing, setIsOverflowing] = useState(false);
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const fullContentRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const checkOverflow = () => {
      if (contentRef.current && fullContentRef.current) {
        const contentRect = contentRef.current.getBoundingClientRect();
        const fullContentRect = fullContentRef.current.getBoundingClientRect();

        const isWidthOverflowing = fullContentRect.width > contentRect.width;
        const isHeightOverflowing = fullContentRect.height > contentRect.height;

        setIsOverflowing(isWidthOverflowing || isHeightOverflowing);
      }
    };

    checkOverflow();
    window.addEventListener("resize", checkOverflow);
    return () => window.removeEventListener("resize", checkOverflow);
  }, []);

  if (!settings?.enterpriseSettings?.custom_header_content) {
    return null;
  }

  return (
    <div
      className={`
        px-2
        z-[39] 
        py-1.5
        text-wrap
        w-full
        mx-auto
        relative
        cursor-default
        shadow-sm
        rounded
        border-l-8 border-l-400
        bg-background
        border-r-4 border-r-200
        border-border
        border
        flex`}
    >
      <div className="text-emphasis text-sm w-full">
        <div className="relative">
          <div className={`flex justify-center w-full overflow-hidden pr-8`}>
            <div
              ref={contentRef}
              className={`overflow-hidden ${settings.enterpriseSettings.two_lines_for_chat_header ? "line-clamp-2" : "line-clamp-1"} text-center max-w-full`}
            >
              <MinimalMarkdown
                className="prose text-sm max-w-full"
                content={settings.enterpriseSettings.custom_header_content}
              />
            </div>
          </div>
          <div className="absolute top-0 left-0 invisible flex justify-center max-w-full">
            <div
              ref={fullContentRef}
              className={`overflow-hidden invisible ${settings.enterpriseSettings.two_lines_for_chat_header ? "line-clamp-2" : "line-clamp-1"} text-center max-w-full`}
            >
              <MinimalMarkdown
                className="prose text-sm max-w-full"
                content={settings.enterpriseSettings.custom_header_content}
              />
            </div>
          </div>
          <div className="absolute bottom-0 right-0">
            {isOverflowing && (
              <Popover
                open={isPopoverOpen}
                onOpenChange={setIsPopoverOpen}
                content={
                  <button
                    onClick={() => setIsPopoverOpen(true)}
                    className="cursor-poiner bg-background-100 p-1 rounded-full"
                  >
                    <ChevronDownIcon className="h-4 w-4 text-emphasis" />
                  </button>
                }
                popover={
                  <div className="bg-background-100 p-4 rounded shadow-lg mobile:max-w-xs desktop:max-w-md">
                    <p className="text-lg font-bold">Banner Content</p>
                    <MinimalMarkdown
                      className="max-h-96 overflow-y-auto"
                      content={
                        settings.enterpriseSettings.custom_header_content
                      }
                    />
                  </div>
                }
                side="bottom"
                align="end"
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
