"use client";

import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import { cn } from "@/lib/utils";
import { OnyxIcon } from "@/components/icons/icons";

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
  size,
  className,
}: {
  logoSrc?: string;
  size: number;
  className?: string;
}) {
  return logoSrc ? (
    <img
      src={logoSrc}
      alt="Logo"
      style={{
        objectFit: "contain",
        height: `${size}px`,
        width: `${size}px`,
      }}
      className={cn("flex-shrink-0", className)}
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
              "rounded-08 border border-transparent px-1 py-0.5 transition-colors",
              highlightTarget === "sidebar" && "border-theme-primary-05"
            )}
          >
            <div className="flex flex-row items-center justify-start w-28 gap-1 origin-top-left scale-75">
              {logoDisplayStyle !== "name_only" && (
                <PreviewLogo logoSrc={logoSrc} size={18} />
              )}
              {(logoDisplayStyle === "logo_and_name" ||
                logoDisplayStyle === "name_only") && (
                <Truncated headingH3>{applicationDisplayName}</Truncated>
              )}
            </div>
          </div>
        </div>
      </div>
      {/* Chat */}
      <div className="flex flex-col flex-1 h-full">
        {/* Chat Body */}
        <div className="flex flex-col flex-1 h-full items-center justify-center px-3">
          <div
            className={cn(
              "flex flex-row items-center justify-center gap-2 mb-2 rounded-08 border border-transparent px-2 py-1 transition-colors",
              highlightTarget === "greeting" && "border-theme-primary-05"
            )}
          >
            <PreviewLogo logoSrc={logoSrc} size={18} />
            <Text text04 headingH3>
              {greeting_message}
            </Text>
          </div>
          <InputPreview />
        </div>
        {/* Chat Footer */}
        <div className="flex flex-col items-center justify-end p-2 w-full">
          <div
            className={cn(
              "flex gap-1 items-start justify-center px-1 py-0.5 rounded-04 border border-transparent transition-colors",
              highlightTarget === "chat_footer" && "border-theme-primary-05"
            )}
          >
            <Text text03 className="origin-top-left scale-75">
              {chat_footer_content}
            </Text>
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
      <div className="flex justify-center p-2 w-full">
        <div
          className={cn(
            "rounded-08 border border-transparent px-2 py-1 transition-colors",
            highlightTarget === "chat_header" && "border-theme-primary-05"
          )}
        >
          <Text text03 className="origin-top-left scale-75">
            {chat_header_content}
          </Text>
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
      <div className="flex flex-col items-center justify-end p-2 w-full">
        <div
          className={cn(
            "flex gap-1 items-start justify-center px-1 py-0.5 rounded-04 border border-transparent transition-colors",
            highlightTarget === "chat_footer" && "border-theme-primary-05"
          )}
        >
          <Text text03 className="origin-top-left scale-75">
            {chat_footer_content}
          </Text>
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
