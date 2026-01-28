import React from "react";
import { SvgExpand } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";

export interface CollapsedHeaderProps {
  totalSteps: number;
  collapsible: boolean;
  onToggle: () => void;
}

/** Header when completed + collapsed - tools summary + step count */
export const CollapsedHeader = React.memo(function CollapsedHeader({
  totalSteps,
  collapsible,
  onToggle,
}: CollapsedHeaderProps) {
  return (
    <>
      <div className="flex items-center gap-2"></div>
      {collapsible && totalSteps > 0 && (
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
