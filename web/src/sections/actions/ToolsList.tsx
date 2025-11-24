"use client";

import React from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import ToolItem from "./ToolItem";
import ToolItemSkeleton from "./skeleton/ToolItemSkeleton";

export interface Tool {
  id: string;
  name: string;
  description: string;
  icon?: React.ReactNode;
  isAvailable: boolean;
  isEnabled: boolean;
}

interface ToolsListProps {
  tools: Tool[];
  searchQuery?: string;
  onToolToggle?: (toolId: string, enabled: boolean) => void;
  className?: string;
  isInitialToolsFetching?: boolean;
}

const ToolsList: React.FC<ToolsListProps> = ({
  tools,
  searchQuery,
  onToolToggle,
  className,
  isInitialToolsFetching,
}) => {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 items-start max-h-[480px] overflow-y-auto w-full",
        className
      )}
    >
      {isInitialToolsFetching ? (
        // Show 5 skeleton items while loading
        <>
          {[...Array(5)].map((_, index) => (
            <ToolItemSkeleton key={`skeleton-${index}`} />
          ))}
        </>
      ) : tools.length > 0 ? (
        tools.map((tool) => (
          <ToolItem
            key={tool.id}
            name={tool.name}
            description={tool.description}
            icon={tool.icon}
            isAvailable={tool.isAvailable}
            isEnabled={tool.isEnabled}
            onToggle={(enabled) => onToolToggle?.(tool.id, enabled)}
          />
        ))
      ) : (
        <div className="flex items-center justify-center w-full py-8">
          <Text text03 mainUiBody>
            {searchQuery ? "No tools found" : "No tools available"}
          </Text>
        </div>
      )}
    </div>
  );
};

ToolsList.displayName = "ToolsList";
export default ToolsList;
