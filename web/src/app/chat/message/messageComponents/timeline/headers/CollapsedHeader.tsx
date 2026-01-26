import React from "react";
import { SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import type { UniqueTool } from "@/app/chat/message/messageComponents/timeline/hooks";

export interface CollapsedHeaderProps {
  uniqueTools: UniqueTool[];
  totalSteps: number;
  collapsible: boolean;
  onToggle: () => void;
}

/** Header when completed + collapsed - tools summary + step count */
export const CollapsedHeader = React.memo(function CollapsedHeader({
  uniqueTools,
  totalSteps,
  collapsible,
  onToggle,
}: CollapsedHeaderProps) {
  return (
    <>
      <div className="flex items-center gap-2">
        {uniqueTools.map((tool) => (
          <div
            key={tool.key}
            className="inline-flex items-center gap-1 rounded-08 p-1 bg-background-tint-02"
          >
            {tool.icon}
            <Text as="span" secondaryBody text04>
              {tool.name}
            </Text>
          </div>
        ))}
      </div>
      {collapsible && (
        <Button
          tertiary
          onClick={onToggle}
          rightIcon={SvgExpand}
          aria-label="Expand timeline"
          aria-expanded={false}
        >
          {totalSteps} {totalSteps === 1 ? "step" : "steps"}
        </Button>
      )}
    </>
  );
});
