"use client";

import React from "react";
import type { Components } from "react-markdown";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import { cn, ensureHrefProtocol } from "@/lib/utils";
import { OnyxIcon } from "@/components/icons/icons";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";

const previewMarkdownComponents = {
  p: ({ children }) => (
    <Text as="p" text03 figureSmallValue className="!my-0 text-center">
      {children}
    </Text>
  ),
  a: ({ node, href, className, children, ...rest }) => {
    const fullHref = ensureHrefProtocol(href);
    return (
      <a
        href={fullHref}
        target="_blank"
        rel="noopener noreferrer"
        {...rest}
        className={cn(className, "underline underline-offset-2")}
      >
        <Text as="span" text03 figureSmallValue>
          {children}
        </Text>
      </a>
    );
  },
} satisfies Partial<Components>;

const PreviewMinimalMarkdown = React.memo(function PreviewMinimalMarkdown({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <MinimalMarkdown
      content={content}
      className={className}
      components={previewMarkdownComponents}
    />
  );
});

export type PreviewHighlightTarget =
  | "sidebar"
  | "greeting"
  | "chat_header"
  | "chat_footer";

export interface PreviewProps {
  logoDisplayStyle: "logo_and_name" | "logo_only" | "name_only";
  applicationDisplayName: string;
  chat_footer_content: string;
  chat_header_content: string;
  greeting_message: string;
  className?: string;
  logoSrc?: string;
  highlightTarget?: PreviewHighlightTarget | null;
}

function PreviewLogo({
  logoSrc,
  forceOnyxIcon,
  size,
  className,
}: {
  logoSrc?: string;
  forceOnyxIcon?: boolean;
  size: number;
  className?: string;
}) {
  return logoSrc && !forceOnyxIcon ? (
    <img
      src={logoSrc}
      alt="Logo"
      style={{
        objectFit: "cover",
        height: `${size}px`,
        width: `${size}px`,
      }}
      className={cn("flex-shrink-0 rounded-full", className)}
    />
  ) : (
    <OnyxIcon size={size} className={cn("flex-shrink-0", className)} />
  );
}

export function InputPreview() {
  return (
    <div className="bg-background-neutral-00 border border-border-01 flex flex-col gap-1.5 items-end pb-1 pl-2.5 pr-1 pt-2.5 rounded-08 w-full h-14">
      <div className="h-5 w-5 bg-theme-primary-05 mt-auto rounded-[0.25rem]"></div>
    </div>
  );
}

function PreviewStart({
  logoDisplayStyle,
  applicationDisplayName,
  chat_footer_content,
  chat_header_content,
  greeting_message,
  logoSrc,
  highlightTarget,
}: PreviewProps) {
  return (
    <div className="flex h-60 rounded-12 shadow-00 bg-background-tint-01 relative">
      {/* Sidebar */}
      <div className="flex w-[6rem] h-full bg-background-tint-02 rounded-l-12 p-1 justify-start">
        <div className="flex flex-col h-fit w-full justify-start">
          <div
            className={cn(
              "inline-flex max-w-full items-center justify-start gap-1 rounded-08 p-0.5 overflow-hidden",
              highlightTarget === "sidebar" && "bg-highlight-match"
            )}
          >
            {logoDisplayStyle !== "name_only" && (
              <PreviewLogo
                logoSrc={logoSrc}
                size={16}
                forceOnyxIcon={
                  logoDisplayStyle === "logo_and_name" &&
                  !applicationDisplayName
                }
              />
            )}
            {(logoDisplayStyle === "logo_and_name" ||
              logoDisplayStyle === "name_only") && (
              <Truncated mainUiAction text04 nowrap>
                {applicationDisplayName || "Onyx"}
              </Truncated>
            )}
          </div>
        </div>
      </div>
      {/* Chat */}
      <div className="flex flex-col flex-1 h-full">
        {/* Chat Body */}
        <div className="flex flex-col flex-1 h-full items-center justify-center px-3">
          <div className="flex w-full max-w-[300px] flex-col items-center justify-center">
            <div
              className={cn(
                "inline-flex max-w-full items-center justify-center gap-1 mb-2 rounded-08 border border-transparent p-0.5 text-center",
                highlightTarget === "greeting" && "bg-highlight-match"
              )}
            >
              <PreviewLogo logoSrc={logoSrc} size={18} />
              <Text
                text04
                headingH3
                className="max-w-[260px] whitespace-normal break-words text-center"
              >
                {greeting_message}
              </Text>
            </div>
            <InputPreview />
          </div>
        </div>
        {/* Chat Footer */}
        <div className="flex flex-col items-center justify-end w-full">
          <div className="flex w-full max-w-[300px] justify-center">
            <div
              className={cn(
                "inline-flex max-w-full items-start justify-center rounded-04 border border-transparent p-0.5 text-center",
                highlightTarget === "chat_footer" && "bg-highlight-match"
              )}
            >
              <PreviewMinimalMarkdown
                content={chat_footer_content}
                className={cn("max-w-full text-center origin-center")}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function PreviewChat({
  chat_header_content,
  chat_footer_content,
  highlightTarget,
}: {
  chat_header_content: string;
  chat_footer_content: string;
  highlightTarget?: PreviewHighlightTarget | null;
}) {
  return (
    <div className="flex flex-col h-60 relative bg-background-tint-01 rounded-12 shadow-00">
      {/* Header */}
      <div className="flex justify-center w-full">
        <div className="flex w-full max-w-[300px] justify-center">
          <div
            className={cn(
              "inline-flex max-w-full items-center justify-center rounded-08 border border-transparent p-0.5 text-center",
              highlightTarget === "chat_header" && "bg-highlight-match"
            )}
          >
            <Text
              figureSmallLabel
              text03
              className="max-w-full whitespace-normal break-words text-center"
            >
              {chat_header_content}
            </Text>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex flex-1 flex-col gap-2 items-center justify-end max-w-[300px] w-full px-3 py-0 mx-auto">
        {/* User message bubble (right side) */}
        <div className="flex flex-col items-end w-full">
          <div className="bg-background-tint-02 flex flex-col items-start px-2.5 py-2 rounded-bl-[10px] rounded-tl-[10px] rounded-tr-[10px]">
            <div className="bg-background-neutral-03 h-1.5 rounded-04 w-20" />
          </div>
        </div>

        {/* AI response bubble (left side) */}
        <div className="flex flex-col gap-1.5 items-start pl-2 pr-16 py-2 w-full">
          <div className="bg-background-neutral-03 h-1.5 rounded-04 w-full" />
          <div className="bg-background-neutral-03 h-1.5 rounded-04 w-full" />
          <div className="bg-background-neutral-03 h-1.5 rounded-04 w-12" />
        </div>

        {/* Input field */}
        <InputPreview />
      </div>

      {/* Footer */}
      <div className="flex flex-col items-center justify-end w-full">
        <div className="flex w-full max-w-[300px] justify-center">
          <div
            className={cn(
              "inline-flex max-w-full items-start justify-center rounded-04 border border-transparent p-0.5 text-center",
              highlightTarget === "chat_footer" && "bg-highlight-match"
            )}
          >
            <PreviewMinimalMarkdown
              content={chat_footer_content}
              className={cn("max-w-full text-center origin-center")}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
export function Preview({
  logoDisplayStyle,
  applicationDisplayName,
  chat_footer_content,
  chat_header_content,
  greeting_message,
  logoSrc,
  className,
  highlightTarget,
}: PreviewProps) {
  return (
    <div className={cn("grid grid-cols-2 gap-2", className)}>
      <PreviewStart
        logoDisplayStyle={logoDisplayStyle}
        applicationDisplayName={applicationDisplayName}
        chat_footer_content={chat_footer_content}
        chat_header_content={chat_header_content}
        greeting_message={greeting_message}
        logoSrc={logoSrc}
        highlightTarget={highlightTarget}
      />
      <PreviewChat
        chat_header_content={chat_header_content}
        chat_footer_content={chat_footer_content}
        highlightTarget={highlightTarget}
      />
    </div>
  );
}
