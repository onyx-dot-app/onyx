"use client";

import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { SvgGlobe } from "@opal/icons";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

/**
 * WebFetchBody - Body for the webfetch tool.
 *
 * Header shows the URL (lifted from description), body shows the response
 * preview in a scrollable block.
 */
export default function WebFetchBody({ toolCall }: ToolCardBodyProps) {
  const url = toolCall.description;
  const body = toolCall.rawOutput;

  return (
    <div className="rounded-08 border-[0.5px] bg-background-neutral-01 border-border-01 overflow-hidden">
      {url && (
        <div
          className={cn(
            "px-3 py-2 border-b-[0.5px] border-border-01",
            "bg-background-tint-01 flex items-center gap-2"
          )}
        >
          <SvgGlobe className="size-3.5 stroke-text-03 shrink-0" />
          <span className="truncate min-w-0">
            <Text font="secondary-mono" color="text-04" nowrap>
              {url}
            </Text>
          </span>
        </div>
      )}
      <div className="p-3 overflow-auto max-h-[18rem] whitespace-pre-wrap wrap-break-word">
        <Text as="p" font="secondary-mono" color="text-03">
          {body || "No response body"}
        </Text>
      </div>
    </div>
  );
}
