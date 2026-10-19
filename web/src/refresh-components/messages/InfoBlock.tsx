"use client";

import { OverflowText } from "@opal/components";
import React, { memo } from "react";
import { cn } from "@opal/utils";
import type { IconProps } from "@opal/types";

export interface InfoBlockProps extends React.HTMLAttributes<HTMLDivElement> {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description?: string;
  iconClassName?: string;
}

const InfoBlockInner = React.forwardRef<HTMLDivElement, InfoBlockProps>(
  (
    { icon: Icon, title, description, iconClassName, className, ...props },
    ref
  ) => {
    return (
      <div
        ref={ref}
        className={cn("flex flex-row items-start gap-1", className)}
        {...props}
      >
        {/* Icon Container */}
        <div className="flex items-center justify-center p-0.5 size-5 shrink-0">
          <Icon className={cn("size-4 stroke-text-02", iconClassName)} />
        </div>

        {/* Text Content */}
        <div className="flex flex-col flex-1 items-start min-w-0">
          <OverflowText
            as="p"
            textPosition="text-start"
            font="main-ui-action"
            color="text-04"
          >
            {title}
          </OverflowText>
          {description && (
            <OverflowText
              as="p"
              textPosition="text-start"
              font="secondary-body"
              color="text-03"
            >
              {description}
            </OverflowText>
          )}
        </div>
      </div>
    );
  }
);
const InfoBlock = memo(InfoBlockInner);
InfoBlock.displayName = "InfoBlock";

export default InfoBlock;
