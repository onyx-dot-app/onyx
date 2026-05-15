import { cn } from "@opal/utils";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import { Content } from "@opal/layouts";
import { IconProps } from "@opal/types";
import React from "react";

export {
  Section,
  widthClassmap,
  heightClassmap,
  type FlexDirection,
  type JustifyContent,
  type AlignItems,
  type Length,
  type SectionProps,
} from "@opal/layouts/general/components";

import { Section } from "@opal/layouts/general/components";

export interface AttachmentItemLayoutProps {
  title: string;
  description: string;
  icon: React.FunctionComponent<IconProps>;
  middleText?: string;
  rightChildren?: React.ReactNode;
}
function AttachmentItemLayout({
  title,
  description,
  icon: Icon,
  middleText,
  rightChildren,
}: AttachmentItemLayoutProps) {
  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      gap={0.25}
      padding={0.25}
    >
      <div className={cn("h-9 aspect-square rounded-08 shrink-0")}>
        <Section>
          <div
            className="attachment-button__icon-wrapper"
            data-testid="attachment-item-icon-wrapper"
          >
            <Icon className="attachment-button__icon" />
          </div>
        </Section>
      </div>
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        gap={1.5}
        className="min-w-0"
      >
        <div data-testid="attachment-item-title" className="flex-1 min-w-0">
          <Content
            title={title}
            description={description}
            sizePreset="main-ui"
            variant="section"
            width="full"
          />
        </div>
        {middleText && (
          <div className="flex-1 min-w-0">
            <Truncated text03 secondaryBody>
              {middleText}
            </Truncated>
          </div>
        )}
        {rightChildren && <div className="shrink-0 px-1">{rightChildren}</div>}
      </Section>
    </Section>
  );
}

export interface CardItemLayoutProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description?: string;
  rightChildren?: React.ReactNode;
}
function CardItemLayout({
  icon: Icon,
  title,
  description,
  rightChildren,
}: CardItemLayoutProps) {
  return (
    <div className="flex flex-col flex-1 self-stretch items-center gap-1 p-1">
      <div className="flex flex-row self-stretch items-center justify-between gap-1">
        <div className="flex flex-row items-center self-stretch p-1.5 gap-1.5">
          <div className="px-0.5">
            <Icon size={18} />
          </div>
          <Truncated mainContentBody>{title}</Truncated>
        </div>

        {rightChildren && (
          <div className={cn("flex flex-row p-0.5 items-center")}>
            {rightChildren}
          </div>
        )}
      </div>

      {description && (
        <div className="pb-1 px-2 flex self-stretch">
          <Text
            as="p"
            secondaryBody
            text03
            className="line-clamp-2 truncate whitespace-normal h-[2.2rem] wrap-break-word"
          >
            {description}
          </Text>
        </div>
      )}
    </div>
  );
}

export { CardItemLayout, AttachmentItemLayout };
