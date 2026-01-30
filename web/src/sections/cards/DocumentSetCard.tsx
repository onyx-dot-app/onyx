"use client";

import { DocumentSetSummary } from "@/lib/types";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { SvgFiles } from "@opal/icons";
import Hoverable, { HoverableContainer } from "@/refresh-components/Hoverable";
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
        <Hoverable
          asChild
          onClick={
            disabled || isSelected === undefined
              ? undefined
              : () => onSelectToggle?.(!isSelected)
          }
          nonInteractive={disabled || isSelected === undefined}
        >
          <HoverableContainer
            padding={0}
            rounded="rounded-12"
            width="fit"
            border
            data-testid={`document-set-card-${documentSet.id}`}
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
          </HoverableContainer>
        </Hoverable>
      </div>
    </SimpleTooltip>
  );
}
