"use client";

import React, { memo } from "react";
import { BooleanFormField } from "@/components/Field";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { FastField } from "formik";
const MAX_DESCRIPTION_LENGTH = 300;

// Memoized individual tool checkbox - only re-renders when its specific props change
const MemoizedToolCheckbox = memo(function MemoizedToolCheckbox({
  toolId,
  displayName,
  description,
}: {
  toolId: number;
  displayName: string;
  description: string;
}) {
  return (
    <FastField name={`enabled_tools_map.${toolId}`}>
      {() => (
        <BooleanFormField
          name={`enabled_tools_map.${toolId}`}
          label={displayName}
          subtext={description}
        />
      )}
    </FastField>
  );
});

// Memoized tool list component
export const MemoizedToolList = memo(function MemoizedToolList({
  tools,
}: {
  tools: ToolSnapshot[];
}) {
  return (
    <>
      {tools.map((tool) => (
        <MemoizedToolCheckbox
          key={tool.id}
          toolId={tool.id}
          displayName={tool.display_name}
          description={
            tool.description && tool.description.length > MAX_DESCRIPTION_LENGTH
              ? tool.description.slice(0, MAX_DESCRIPTION_LENGTH) + "…"
              : tool.description
          }
        />
      ))}
    </>
  );
});

// Memoized MCP server tools section
export const MemoizedMCPServerTools = memo(function MemoizedMCPServerTools({
  serverId,
  serverTools,
}: {
  serverId: number;
  serverTools: ToolSnapshot[];
}) {
  return (
    <div className="ml-7 space-y-2">
      {serverTools.map((tool) => (
        <MemoizedToolCheckbox
          key={tool.id}
          toolId={tool.id}
          displayName={tool.display_name}
          description={tool.description}
        />
      ))}
    </div>
  );
});
