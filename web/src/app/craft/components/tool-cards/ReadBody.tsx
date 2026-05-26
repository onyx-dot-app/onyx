"use client";

import { useState } from "react";
import { cn } from "@opal/utils";
import { Text, Button } from "@opal/components";
import { SvgChevronDown } from "@opal/icons";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

const PREVIEW_LINE_COUNT = 10;

/**
 * ReadBody - File preview for the read tool.
 *
 * Renders the first N lines with line numbers in a code-editor-style
 * card. Expands to show the full file on demand.
 */
export default function ReadBody({ toolCall }: ToolCardBodyProps) {
  const [expanded, setExpanded] = useState(false);
  const content = toolCall.rawOutput;

  if (!content) {
    return (
      <div
        className={cn(
          "rounded-08 border-[0.5px] overflow-hidden px-3 py-2",
          "bg-background-neutral-01 border-border-01"
        )}
      >
        <Text font="secondary-mono" color="text-03">
          (empty file)
        </Text>
      </div>
    );
  }

  const allLines = content.split("\n");
  const totalLines = allLines.length;
  const visibleLines = expanded
    ? allLines
    : allLines.slice(0, PREVIEW_LINE_COUNT);
  const hiddenCount = totalLines - visibleLines.length;

  return (
    <div
      className={cn(
        "rounded-08 border-[0.5px] overflow-hidden",
        "bg-background-neutral-01 border-border-01"
      )}
    >
      <div className="overflow-auto max-h-[24rem]">
        <table className="w-full">
          <tbody>
            {visibleLines.map((line, idx) => (
              <tr key={idx} className="align-baseline">
                <td className="select-none pl-1.5 pr-1.5 py-0 text-right align-baseline w-8 border-r-[0.5px] border-border-01 bg-background-tint-01">
                  <Text font="secondary-mono" color="text-02">
                    {String(idx + 1)}
                  </Text>
                </td>
                <td className="pl-2 pr-2 py-0 whitespace-pre-wrap wrap-break-word">
                  <Text font="secondary-mono" color="text-04">
                    {line || " "}
                  </Text>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hiddenCount > 0 && (
        <div
          className={cn(
            "px-2 py-1 border-t-[0.5px] border-border-01",
            "bg-background-tint-01 flex items-center justify-between"
          )}
        >
          <Text font="secondary-body" color="text-02">
            {`${hiddenCount} more line${hiddenCount === 1 ? "" : "s"}`}
          </Text>
          <Button
            variant="default"
            prominence="tertiary"
            size="2xs"
            icon={SvgChevronDown}
            onClick={() => setExpanded(true)}
          >
            Show all
          </Button>
        </div>
      )}
    </div>
  );
}
