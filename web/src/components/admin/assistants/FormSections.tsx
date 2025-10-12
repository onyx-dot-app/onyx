"use client";

import React, { memo } from "react";
import { FastField, useFormikContext } from "formik";
import { TextFormField } from "@/components/Field";
import { FiChevronRight, FiChevronDown } from "react-icons/fi";

const MAX_DESCRIPTION_LENGTH = 600;
import { useState, useEffect } from "react";

// Isolated Name Field that only re-renders when its value changes
export const NameField = memo(function NameField() {
  return (
    <FastField name="name">
      {({ field }: any) => (
        <TextFormField
          {...field}
          maxWidth="max-w-lg"
          name="name"
          label="Name"
          placeholder="Email Assistant"
          aria-label="assistant-name-input"
          className="[&_input]:placeholder:text-text-muted/50"
        />
      )}
    </FastField>
  );
});

// Isolated Description Field
export const DescriptionField = memo(function DescriptionField() {
  return (
    <FastField name="description">
      {({ field }: any) => (
        <TextFormField
          {...field}
          maxWidth="max-w-lg"
          name="description"
          label="Description"
          placeholder="Use this Assistant to help draft professional emails"
          className="[&_input]:placeholder:text-text-muted/50"
        />
      )}
    </FastField>
  );
});

// Isolated System Prompt Field
export const SystemPromptField = memo(function SystemPromptField() {
  return (
    <FastField name="system_prompt">
      {({ field }: any) => (
        <TextFormField
          {...field}
          maxWidth="max-w-4xl"
          name="system_prompt"
          label="Instructions"
          isTextArea={true}
          placeholder="You are a professional email writing assistant that always uses a polite enthusiastic tone, emphasizes action items, and leaves blanks for the human to fill in when you have unknowns"
          data-testid="assistant-instructions-input"
          className="[&_textarea]:placeholder:text-text-muted/50"
        />
      )}
    </FastField>
  );
});

// Isolated Task Prompt Field
export const TaskPromptField = memo(function TaskPromptField() {
  return (
    <FastField name="task_prompt">
      {({ field, form }: any) => (
        <TextFormField
          {...field}
          maxWidth="max-w-4xl"
          name="task_prompt"
          label="[Optional] Reminders"
          isTextArea={true}
          placeholder="Remember to reference all of the points mentioned in my message to you and focus on identifying action items that can move things forward"
          onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
            form.setFieldValue("task_prompt", e.target.value);
          }}
          explanationText="Learn about prompting in our docs!"
          explanationLink="https://docs.onyx.app/admin/agents/overview"
          className="[&_textarea]:placeholder:text-text-muted/50"
        />
      )}
    </FastField>
  );
});

// Memoized MCP Server Section that only re-renders when its specific data changes
export const MCPServerSection = memo(function MCPServerSection({
  serverId,
  serverTools,
  serverName,
  serverUrl,
  isCollapsed,
  onToggleCollapse,
  onToggleServerTools,
}: {
  serverId: number;
  serverTools: any[];
  serverName: string;
  serverUrl: string;
  isCollapsed: boolean;
  onToggleCollapse: (serverId: number) => void;
  onToggleServerTools: () => void;
}) {
  const { values } = useFormikContext<any>();
  const [expandedToolDescriptions, setExpandedToolDescriptions] = useState<
    Record<number, boolean>
  >({});

  // Calculate checkbox state locally
  const enabledCount = serverTools.filter(
    (tool) => values.enabled_tools_map[tool.id]
  ).length;

  const checkboxState =
    enabledCount === 0
      ? false
      : enabledCount === serverTools.length
        ? true
        : "indeterminate";

  return (
    <div className="border rounded-lg p-4 space-y-3 dark:border-gray-700">
      <div className="flex items-center space-x-3">
        <button
          type="button"
          onClick={() => onToggleCollapse(serverId)}
          className="flex-shrink-0 p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
        >
          {isCollapsed ? (
            <FiChevronRight className="w-4 h-4 text-gray-600 dark:text-gray-400" />
          ) : (
            <FiChevronDown className="w-4 h-4 text-gray-600 dark:text-gray-400" />
          )}
        </button>
        <input
          type="checkbox"
          checked={checkboxState === true}
          ref={(el) => {
            if (el) el.indeterminate = checkboxState === "indeterminate";
          }}
          onChange={onToggleServerTools}
          className="w-4 h-4 text-blue-600 bg-gray-100 dark:bg-gray-700 border-gray-300 dark:border-gray-600 rounded focus:ring-blue-500"
        />
        <div className="flex-grow">
          <div className="font-medium text-sm text-gray-900 dark:text-gray-100">
            {serverName}
          </div>
          <div className="text-xs text-gray-600 dark:text-gray-400">
            {serverUrl} ({serverTools.length} tools)
          </div>
        </div>
      </div>
      {!isCollapsed && (
        <div className="ml-7 space-y-2">
          {serverTools.map((tool) => (
            <FastField
              key={`${tool.id}-${
                expandedToolDescriptions[tool.id] ? "expanded" : "collapsed"
              }`}
              name={`enabled_tools_map.${tool.id}`}
            >
              {({ field, form }: any) => (
                <label className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    checked={field.value || false}
                    onChange={(e) => {
                      form.setFieldValue(field.name, e.target.checked);
                    }}
                    className="w-4 h-4"
                  />
                  <div>
                    <div className="text-sm font-medium">
                      {tool.display_name}
                    </div>
                    <div className="text-xs text-gray-600">
                      {tool.description &&
                      tool.description.length > MAX_DESCRIPTION_LENGTH ? (
                        <>
                          {expandedToolDescriptions[tool.id]
                            ? tool.description
                            : `${tool.description.slice(
                                0,
                                MAX_DESCRIPTION_LENGTH
                              )}... `}
                          <button
                            type="button"
                            className="ml-1 text-blue-500 underline text-xs focus:outline-none"
                            onClick={() =>
                              setExpandedToolDescriptions(
                                (prev: Record<number, boolean>) => ({
                                  ...prev,
                                  [tool.id]: !prev[tool.id],
                                })
                              )
                            }
                            tabIndex={0}
                          >
                            {expandedToolDescriptions[tool.id]
                              ? "Show less"
                              : "Expand"}
                          </button>
                        </>
                      ) : (
                        tool.description
                      )}
                    </div>
                  </div>
                </label>
              )}
            </FastField>
          ))}
        </div>
      )}
    </div>
  );
});
