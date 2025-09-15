"use client";

import { DocumentSetSummary, ValidSources } from "@/lib/types";
import { CustomCheckbox } from "../CustomCheckbox";
import { SourceIcon } from "../SourceIcon";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function DocumentSetSelectable({
  documentSet,
  isSelected,
  onSelect,
  disabled,
  disabledTooltip,
}: {
  documentSet: DocumentSetSummary;
  isSelected: boolean;
  onSelect: () => void;
  disabled?: boolean;
  disabledTooltip?: string;
}) {
  // Collect unique connector sources
  const uniqueSources = new Set<ValidSources>();
  documentSet.cc_pair_summaries.forEach((ccPairSummary) => {
    uniqueSources.add(ccPairSummary.source);
  });

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={`
              w-72
              px-3 
              py-1
              rounded-lg 
              border
              border-border
              ${disabled ? "bg-background" : ""}
              flex 
              cursor-pointer 
              ${
                isSelected
                  ? "bg-accent-background-hovered"
                  : "bg-background hover:bg-accent-background"
              }
            `}
            onClick={disabled ? undefined : onSelect}
          >
            <div className="flex w-full">
              <div className="flex flex-col h-full">
                <div className="font-bold">{documentSet.name}</div>
                <div className="text-xs">{documentSet.description}</div>
                <div className="flex gap-x-2 pt-1 mt-auto mb-1">
                  {Array.from(uniqueSources).map((source) => (
                    <SourceIcon
                      key={source}
                      sourceType={source}
                      iconSize={16}
                    />
                  ))}
                </div>
              </div>
              <div className="ml-auto my-auto pl-1">
                <CustomCheckbox
                  checked={isSelected}
                  onChange={() => null}
                  disabled={disabled}
                />
              </div>
            </div>
          </div>
        </TooltipTrigger>
        {disabled && disabledTooltip && (
          <TooltipContent>
            <p>{disabledTooltip}</p>
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
}
