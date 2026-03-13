import React from "react";
import { ContentAction } from "@opal/layouts";
import type { IconProps } from "@opal/types";

export interface NameCardProps {
  icon?: React.FunctionComponent<IconProps>;
  customIcon?: React.ReactNode;
  title: string;
  description?: string;
  rightChildren?: React.ReactNode;
}

export default function NameCard({
  icon,
  customIcon,
  title,
  description,
  rightChildren,
}: NameCardProps) {
  return (
    <div className="bg-background-tint-01 p-2 w-full rounded-08">
      <ContentAction
        icon={customIcon ? () => <>{customIcon}</> : icon}
        title={title}
        description={description}
        sizePreset="main-ui"
        variant="section"
        rightChildren={rightChildren}
        paddingVariant="fit"
      />
    </div>
  );
}
