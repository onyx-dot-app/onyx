import SvgChevronDown from "@/icons/chevron-down";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import React from "react";

interface ToolsSectionProps {
  serverName: string;
  toolCount?: number;
  onViewTools?: () => void;
}

export const ToolsSection: React.FC<ToolsSectionProps> = React.memo(
  ({ serverName, toolCount, onViewTools }) => (
    <div className="flex gap-2 items-center justify-end pl-8 w-full">
      <div className="flex flex-1 min-w-0 px-0.5">
        <Text mainUiAction text04 className="flex-1 min-w-0">
          {toolCount !== undefined
            ? `${toolCount} tool${toolCount !== 1 ? "s" : ""}`
            : "0 tools"}
        </Text>
      </div>
      {onViewTools && (
        <Button
          tertiary
          onClick={onViewTools}
          rightIcon={SvgChevronDown}
          className="shrink-0"
          aria-label={`View tools for ${serverName}`}
        >
          View Tools
        </Button>
      )}
    </div>
  )
);
ToolsSection.displayName = "ToolsSection";
