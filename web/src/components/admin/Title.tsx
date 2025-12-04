"use client";
import { JSX } from "react";
import { HealthCheckBanner } from "../health/healthcheck";
import Separator from "@/refresh-components/Separator";
import { IconProps } from "@/icons";
import Text from "@/refresh-components/texts/Text";

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
      <div className="mb-4">
        <HealthCheckBanner />
      </div>
      <div className="w-full flex flex-row justify-between">
        <div className="flex flex-row gap-2">
          {typeof Icon === "function" ? (
            <Icon className="stroke-text-04 h-8 w-8" />
          ) : (
            Icon
          )}
          <Text headingH2 aria-label="admin-page-title">
            {title}
          </Text>
        </div>
        {farRightElement}
      </div>
      {includeDivider ? <Separator /> : <div className="mb-6" />}
    </div>
  );
}
