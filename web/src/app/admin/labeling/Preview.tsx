"use client";

import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import { cn } from "@/lib/utils";

export interface PreviewProps {
  logoDisplayStyle: "logo_and_name" | "logo_only" | "none";
  applicationDisplayName: string;
  chat_footer_content: string;
  chat_header_content: string;
  greeting_message: string;
  className?: string;
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
}: PreviewProps) {
  return (
    <div className="flex h-60 rounded-12 shadow-00 bg-background-tint-01 relative">
      {/* Sidebar */}
      <div className="flex w-[5.75rem] h-full bg-background-tint-02 rounded-l-12 p-2">
        <div className="flex justify-center h-fit w-full">
          {/* TODO: Add logo here */}
          {logoDisplayStyle === "logo_and_name" && (
            <Text text04 className="origin-top-left scale-75">
              {applicationDisplayName}
            </Text>
          )}
        </div>
      </div>
      {/* Chat */}
      <div className="flex flex-col flex-1 h-full">
        {/* Chat Body */}
        <div className="flex flex-col flex-1 h-full items-center justify-center px-3">
          <Text text04 headingH3>
            {greeting_message}
          </Text>
          <InputPreview />
        </div>
        {/* Chat Footer */}
        <div className="flex flex-col items-center justify-end p-2 w-full">
          <div className="flex gap-1 items-start justify-center px-1 py-0.5 rounded-04">
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
}: {
  chat_header_content: string;
  chat_footer_content: string;
}) {
  return (
    <div className="flex flex-col h-60 relative bg-background-tint-01 rounded-12 shadow-00">
      {/* Header */}
      <div className="flex justify-center p-2 w-full">
        <Text text03 className="origin-top-left scale-75">
          {chat_header_content}
        </Text>
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
        <div className="flex gap-1 items-start justify-center px-1 py-0.5 rounded-04">
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
  className,
}: PreviewProps) {
  return (
    <div className={cn("grid grid-cols-2 gap-2", className)}>
      <PreviewStart
        logoDisplayStyle={logoDisplayStyle}
        applicationDisplayName={applicationDisplayName}
        chat_footer_content={chat_footer_content}
        chat_header_content={chat_header_content}
        greeting_message={greeting_message}
      />
      <PreviewChat
        chat_header_content={chat_header_content}
        chat_footer_content={chat_footer_content}
      />
    </div>
  );
}
