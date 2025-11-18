"use client";

import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { BackButton } from "@/refresh-components/buttons/BackButton";
import Separator from "@/refresh-components/Separator";

export interface SimplePageHeaderProps {
  title: string;
  className?: string;
  rightChildren?: React.ReactNode;
}

export default function SimplePageHeader({
  title,
  className,
  rightChildren,
}: SimplePageHeaderProps) {
  return (
    <div
      className={cn(
        "sticky top-0 z-10 flex flex-col gap-4 px-3 bg-background-tint-01 w-full",
        className
      )}
    >
      <div className="flex flex-col gap-4 pt-6">
        <BackButton />
        <div className="flex flex-col gap-6 px-2">
          <div className="flex flex-row justify-between items-center">
            <Text headingH2>{title}</Text>
            {rightChildren}
          </div>
          <Separator className="my-0" />
        </div>
      </div>
    </div>
  );
}
