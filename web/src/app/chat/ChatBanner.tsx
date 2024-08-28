"use client";

import ReactMarkdown from "react-markdown";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useContext, useState, useRef, useLayoutEffect } from "react";
import remarkGfm from "remark-gfm";
import { Popover } from "@/components/popover/Popover";
import { ChevronDownIcon } from "@/components/icons/icons";
import { Divider } from "@tremor/react";
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
        setIsOverflowing(
          fullContentRef.current.scrollHeight > contentRef.current.clientHeight
        );
      }
    };

    checkOverflow();
    window.addEventListener("resize", checkOverflow);
    return () => window.removeEventListener("resize", checkOverflow);
  }, []);

  if (!settings?.enterpriseSettings?.custom_header_content) {
    return null;
  }

  const renderMarkdown = (className: string) => (
    <ReactMarkdown
      className={`w-full text-wrap break-word ${className}`}
      components={{
        a: ({ node, ...props }) => (
          <a
            {...props}
            className="text-sm text-link hover:text-link-hover"
            target="_blank"
            rel="noopener noreferrer"
          />
        ),
        p: ({ node, ...props }) => (
          <p {...props} className="text-wrap break-word text-sm m-0 w-full" />
        ),
      }}
      remarkPlugins={[remarkGfm]}
    >
      {settings.enterpriseSettings?.custom_header_content}
    </ReactMarkdown>
  );
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
        bg-background-100
        shadow-sm
        rounded
        border-l-8 border-l-400
        border-r-4 border-r-200
        border-border
        border
        flex`}
    >
      <div className="text-emphasis text-sm w-full">
        <div className="relative">
          <div
            ref={contentRef}
            className="line-clamp-2 text-center w-full overflow-hidden pr-8"
          >
            <MinimalMarkdown
              className=""
              content={settings.enterpriseSettings.custom_header_content}
            />
          </div>
          <div
            ref={fullContentRef}
            className="absolute top-0 left-0 invisible w-full"
          >
            <MinimalMarkdown
              className=""
              content={settings.enterpriseSettings.custom_header_content}
            />
          </div>
          <div className="absolute bottom-0 right-0 ">
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
