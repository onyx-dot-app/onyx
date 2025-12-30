import React from "react";
import Text from "@/refresh-components/texts/Text";

export interface CounterSeparatorProps {
  count: number;
  text: string;
}

export default function CounterSeparator({
  count,
  text,
}: CounterSeparatorProps) {
  return (
    <div className="flex flex-row items-center w-full gap-2 px-4">
      <div className="flex-1 h-px bg-border" />
      <div className="flex flex-row items-center gap-1 flex-shrink-0">
        <Text as="p" secondaryBody text03>
          {count}
        </Text>
        <Text as="p" secondaryBody text03>
          {text}
        </Text>
      </div>
      <div className="flex-1 h-px bg-border" />
    </div>
  );
}
