"use client";

import React, { memo, useState, useCallback, useMemo } from "react";
import { useFormikContext } from "formik";
import { Info } from "lucide-react";
import { FiChevronDown, FiChevronRight, FiUsers, FiX } from "react-icons/fi";
import { SearchMultiSelectDropdown } from "@/components/Dropdown";
import Text from "@/refresh-components/texts/Text";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { HoverPopup } from "@/components/HoverPopup";

interface AgentSelectorProps {
  availableAgents: MinimalPersonaSnapshot[];
  currentPersonaId?: number;
}

export const AgentSelector = memo(function AgentSelector({
  availableAgents,
  currentPersonaId,
}: AgentSelectorProps) {
  const { values, setFieldValue } = useFormikContext<any>();
  const [expandedAgentId, setExpandedAgentId] = useState<number | null>(null);

  const filteredAgents = useMemo(
    () =>
      availableAgents.filter(
        (agent) =>
          agent.id !== currentPersonaId &&
          !agent.builtin_persona &&
          agent.is_visible
      ),
    [availableAgents, currentPersonaId]
  );

  const selectedAgentIds: number[] = values.child_persona_ids || [];

  const selectedAgents = useMemo(
    () => filteredAgents.filter((agent) => selectedAgentIds.includes(agent.id)),
    [filteredAgents, selectedAgentIds]
  );

  const handleSelect = useCallback(
    (option: { name: string; value: string | number }) => {
      const agentId =
        typeof option.value === "string"
          ? parseInt(option.value, 10)
          : option.value;
      if (!selectedAgentIds.includes(agentId)) {
        setFieldValue("child_persona_ids", [...selectedAgentIds, agentId]);
      }
    },
    [selectedAgentIds, setFieldValue]
  );

  const handleRemove = useCallback(
    (agentId: number) => {
      setFieldValue(
        "child_persona_ids",
        selectedAgentIds.filter((id) => id !== agentId)
      );
      const configMap = { ...(values.child_persona_configs || {}) };
      delete configMap[agentId];
      setFieldValue("child_persona_configs", configMap);
    },
    [selectedAgentIds, values.child_persona_configs, setFieldValue]
  );

  const toggleExpand = useCallback((agentId: number) => {
    setExpandedAgentId((prev) => (prev === agentId ? null : agentId));
  }, []);

  if (filteredAgents.length === 0) {
    return null;
  }

  const dropdownOptions = filteredAgents
    .filter((agent) => !selectedAgentIds.includes(agent.id))
    .map((agent) => ({
      name: agent.name,
      value: agent.id,
      description: agent.description,
    }));

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        <Text mainUiBody text04>
          Agent Actions
        </Text>
        <HoverPopup
          mainContent={
            <Info className="h-3.5 w-3.5 text-text-400 cursor-help" />
          }
          popupContent={
            <div className="text-xs space-y-2 max-w-xs text-white">
              <div>
                <span className="font-semibold">
                  Allow this agent to invoke other agents as tools
                </span>
              </div>
            </div>
          }
          direction="bottom"
        />
      </div>

      <SearchMultiSelectDropdown
        options={dropdownOptions}
        onSelect={handleSelect}
      />

      {selectedAgents.length > 0 && (
        <div className="flex flex-col gap-2 mt-2">
          {selectedAgents.map((agent) => {
            const isExpanded = expandedAgentId === agent.id;
            const config = values.child_persona_configs?.[agent.id] || {
              pass_conversation_context: true,
              pass_files: false,
              invocation_instructions: "",
            };

            return (
              <div
                key={agent.id}
                className="border rounded-lg p-3 dark:border-gray-700 bg-background-subtle"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => toggleExpand(agent.id)}
                      className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
                    >
                      {isExpanded ? (
                        <FiChevronDown className="w-4 h-4 text-gray-500" />
                      ) : (
                        <FiChevronRight className="w-4 h-4 text-gray-500" />
                      )}
                    </button>
                    <div className="w-6 h-6 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center">
                      <FiUsers className="w-3 h-3 text-blue-600 dark:text-blue-400" />
                    </div>
                    <div>
                      <div className="font-medium text-sm">{agent.name}</div>
                      <div className="text-xs text-gray-500 line-clamp-1 max-w-[200px]">
                        {agent.description}
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleRemove(agent.id)}
                    className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors text-gray-500 hover:text-gray-700"
                  >
                    <FiX className="w-4 h-4" />
                  </button>
                </div>

                {isExpanded && (
                  <div className="mt-3 pt-3 border-t dark:border-gray-700 space-y-3 ml-8">
                    <Text className="text-xs text-gray-500">
                      Configuration for invoking this agent
                    </Text>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <Checkbox
                        checked={config.pass_conversation_context}
                        onCheckedChange={(checked) => {
                          setFieldValue(`child_persona_configs.${agent.id}`, {
                            ...config,
                            persona_id: agent.id,
                            pass_conversation_context: checked,
                          });
                        }}
                      />
                      <span className="text-sm">Pass conversation context</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <Checkbox
                        checked={config.pass_files}
                        onCheckedChange={(checked) => {
                          setFieldValue(`child_persona_configs.${agent.id}`, {
                            ...config,
                            persona_id: agent.id,
                            pass_files: checked,
                          });
                        }}
                      />
                      <span className="text-sm">Pass attached files</span>
                    </label>
                    <div>
                      <label className="text-sm text-gray-600 dark:text-gray-400 mb-1 block">
                        When to invoke (optional)
                      </label>
                      <textarea
                        className="w-full text-sm border rounded p-2 dark:bg-gray-800 dark:border-gray-700"
                        placeholder="e.g., Use this agent when the user asks about..."
                        rows={2}
                        value={config.invocation_instructions || ""}
                        onChange={(e) => {
                          setFieldValue(`child_persona_configs.${agent.id}`, {
                            ...config,
                            persona_id: agent.id,
                            invocation_instructions: e.target.value,
                          });
                        }}
                      />
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
});

export default AgentSelector;
