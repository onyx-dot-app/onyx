"use client";

import { JSX } from "react";
import { Divider, Text } from "@opal/components";
import type { IconProps } from "@opal/types";
import { richNodes } from "@opal/utils";

export interface AdminPageTitleProps {
  icon: React.FunctionComponent<IconProps> | React.ReactNode;
  title: string | JSX.Element;
  farRightElement?: JSX.Element;
  includeDivider?: boolean;
}

export function AdminPageTitle({
  icon: Icon,
  title,
  farRightElement,
  includeDivider = true,
}: AdminPageTitleProps) {
  return (
    <div className="w-full">
      <div className="w-full flex flex-row justify-between">
        <div className="flex flex-row gap-2">
          {typeof Icon === "function" ? (
            <Icon className="stroke-text-04 h-8 w-8" />
          ) : (
            Icon
          )}
          <Text font="heading-h2" color="text-05" aria-label="admin-page-title">
            {typeof title === "string" ? title : richNodes(title)}
          </Text>
        </div>
        {farRightElement}
      </div>
      {includeDivider ? <Divider /> : <div className="mb-6" />}
    </div>
  );
}
