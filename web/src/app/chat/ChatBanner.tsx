"use client";

import ReactMarkdown from "react-markdown";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useContext } from "react";
import remarkGfm from "remark-gfm";

export function ChatBanner() {
  const settings = useContext(SettingsContext);
  if (!settings?.enterpriseSettings?.custom_header_content) {
    return null;
  }

  return (
    <div
      className={`
        mt-8
        mb-2
        mx-2
        z-[39] 
        w-full
        h-[30px]
        bg-background-100
        shadow-sm
        rounded
        border-border
        border
        flex`}
    >
      <div className="mx-auto text-emphasis text-sm flex flex-col">
        <div className="my-auto">
          <ReactMarkdown
            className="prose max-w-full"
            components={{
              a: ({ node, ...props }) => (
                <a
                  {...props}
                  className="text-sm text-link hover:text-link-hover"
                  target="_blank"
                  rel="noopener noreferrer"
                />
              ),
              p: ({ node, ...props }) => <p {...props} className="text-sm" />,
            }}
            remarkPlugins={[remarkGfm]}
          >
            {settings.enterpriseSettings.custom_header_content}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
