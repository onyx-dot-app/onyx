"use client";

import React from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { IconProps } from "@/icons";
import Truncated from "../texts/Truncated";

export interface InfoBlockProps extends React.HTMLAttributes<HTMLDivElement> {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description?: string;
  iconClassName?: string;
}

function InfoBlockInner(
  {
    icon: Icon,
    title,
    description,
    iconClassName,
    className,
    ...props
  }: InfoBlockProps,
  ref: React.ForwardedRef<HTMLDivElement>
) {
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
        <Truncated mainUiAction text04>
          {title}
        </Truncated>
        {description && (
          <Truncated secondaryBody text03>
            {description}
          </Truncated>
        )}
      </div>
    </div>
  );
}

const InfoBlock = React.forwardRef<HTMLDivElement, InfoBlockProps>(
  InfoBlockInner
);
InfoBlock.displayName = "InfoBlock";

export default InfoBlock;
