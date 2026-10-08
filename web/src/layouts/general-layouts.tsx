import { cn } from "@opal/utils";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
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

export { CardItemLayout };
