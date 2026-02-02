import React from "react";
import { SvgFold } from "@opal/icons";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";

export interface ExpandedHeaderProps {
  collapsible: boolean;
  onToggle: () => void;
}

/** Header when completed + expanded */
export const ExpandedHeader = React.memo(function ExpandedHeader({
  collapsible,
  onToggle,
}: ExpandedHeaderProps) {
  return (
    <>
      <Text as="p" mainUiAction text03>
        Thought for some time
      </Text>
      {collapsible && (
        <IconButton
          tertiary
          onClick={onToggle}
          icon={SvgFold}
          aria-label="Collapse timeline"
          aria-expanded={true}
        />
      )}
    </>
  );
});
