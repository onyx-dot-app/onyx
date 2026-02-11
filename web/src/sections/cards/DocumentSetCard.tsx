"use client";

import { DocumentSetSummary } from "@/lib/types";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
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
    <SimpleTooltip
      tooltip={disabled && disabledTooltip ? disabledTooltip : undefined}
      disabled={!disabled || !disabledTooltip}
    >
      <div className="max-w-[12rem]">
        <Interactive.Base
          onClick={
            disabled || isSelected === undefined
              ? undefined
              : () => onSelectToggle?.(!isSelected)
          }
          variant="none"
          static={disabled || isSelected === undefined}
        >
          <Interactive.Container
            border
            data-testid={`document-set-card-${documentSet.id}`}
            heightVariant="fit"
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
        </Interactive.Base>
      </div>
    </SimpleTooltip>
  );
}
