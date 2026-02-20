import React from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";

export interface TextSeparatorProps {
  count?: number;
  text: string;
  className?: string;
}

export default function TextSeparator({
  count,
  text,
  className,
}: TextSeparatorProps) {
  return (
    <div
      className={cn("flex flex-row items-center w-full gap-2 px-4", className)}
    >
      <div className="flex-1 h-px bg-border" />
      <div className="flex flex-row items-center gap-1 flex-shrink-0">
        {count !== undefined && (
          <Text as="p" secondaryBody text03>
            {count}
          </Text>
        )}
        <Text as="p" secondaryBody text03>
          {text}
        </Text>
      </div>
      <div className="flex-1 h-px bg-border" />
    </div>
  );
}
