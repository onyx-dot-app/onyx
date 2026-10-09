"use client";

import { DocumentSetSummary } from "@/lib/types";
import { AttachmentItemButton } from "@opal/components";
import { Interactive } from "@opal/core";
import { SvgFiles } from "@opal/icons";

export interface DocumentSetCardProps {
  documentSet: DocumentSetSummary;
  isSelected?: boolean;
  onSelectToggle?: (isSelected: boolean) => void;
  disabled?: boolean;
  disabledTooltip?: string;
}

export default function DocumentSetCard({
  documentSet,
  isSelected,
  onSelectToggle,
  disabled,
  disabledTooltip,
}: DocumentSetCardProps) {
  const selectable = !disabled && isSelected !== undefined;

  return (
    <div className="max-w-48">
      <Interactive.Container border size="fit" width="full">
        <AttachmentItemButton
          data-testid={`document-set-card-${documentSet.id}`}
          icon={SvgFiles}
          title={documentSet.name}
          description={documentSet.description}
          state={isSelected ? "selected" : undefined}
          onClick={selectable ? () => onSelectToggle?.(!isSelected) : undefined}
          disabled={disabled}
          tooltip={disabled && disabledTooltip ? disabledTooltip : undefined}
        />
      </Interactive.Container>
    </div>
  );
}
