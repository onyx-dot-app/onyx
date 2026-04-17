"use client";

import { DocumentSetSummary } from "@/lib/types";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import { Tooltip } from "@opal/components";
import { SvgFiles } from "@opal/icons";
import { Interactive } from "@opal/core";
import { AttachmentItemLayout } from "@/layouts/general-layouts";
import Spacer from "@/refresh-components/Spacer";

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
  return (
    <Tooltip
      tooltip={disabled && disabledTooltip ? disabledTooltip : undefined}
    >
      <div className="max-w-[12rem]">
        <Interactive.Simple
          onClick={
            disabled || isSelected === undefined
              ? undefined
              : () => onSelectToggle?.(!isSelected)
          }
        >
          <Interactive.Container
            data-testid={`document-set-card-${documentSet.id}`}
            border
            size="fit"
          >
            <AttachmentItemLayout
              icon={SvgFiles}
              title={documentSet.name}
              description={documentSet.description}
              rightChildren={
                isSelected === undefined ? undefined : (
                  <div onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={isSelected}
                      disabled={disabled}
                      onCheckedChange={
                        disabled
                          ? undefined
                          : () => onSelectToggle?.(!isSelected)
                      }
                    />
                  </div>
                )
              }
            />
            <Spacer horizontal rem={0.5} />
          </Interactive.Container>
        </Interactive.Simple>
      </div>
    </Tooltip>
  );
}
