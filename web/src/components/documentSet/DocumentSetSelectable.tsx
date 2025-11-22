"use client";

import { DocumentSetSummary, ValidSources } from "@/lib/types";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import { SourceIcon } from "../SourceIcon";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

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
    <SimpleTooltip
      tooltip={disabled && disabledTooltip ? disabledTooltip : undefined}
      disabled={!disabled || !disabledTooltip}
    >
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
        data-testid={`document-set-card-${documentSet.id}`}
      >
        <div className="flex w-full">
          <div className="flex flex-col h-full">
            <div className="font-bold">{documentSet.name}</div>
            <div className="text-xs">{documentSet.description}</div>
            <div className="flex gap-x-2 pt-1 mt-auto mb-1">
              {Array.from(uniqueSources).map((source) => (
                <SourceIcon key={source} sourceType={source} iconSize={16} />
              ))}
            </div>
          </div>
          <div
            className="ml-auto my-auto pl-1"
            // Prevent the checkbox click from bubbling up to all document set cards.
            // Not sure why this was happening but stopping propogation here while
            // setting onCheckedChanged in the Checkbox component fixes it.
            onClick={(e) => e.stopPropagation()}
          >
            <Checkbox
              checked={isSelected}
              disabled={disabled}
              onCheckedChange={disabled ? undefined : onSelect}
            />
          </div>
        </div>
      </div>
    </SimpleTooltip>
  );
}
