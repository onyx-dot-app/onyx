"use client";

import { useState, useMemo, useCallback } from "react";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useAgents } from "@/hooks/useAgents";
import SelectButton from "@/refresh-components/buttons/SelectButton";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import Switch from "@/refresh-components/inputs/Switch";
import CustomAgentAvatar from "@/refresh-components/avatars/CustomAgentAvatar";
import { SvgCheck, SvgOnyxOctagon } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";

export interface CallableAgentsPopoverProps {
  // The current agent/persona being used (to exclude from the list)
  currentPersonaId: number | null;
  // IDs of personas that are pre-configured as callable in the DB
  preConfiguredCallableIds: number[];
  // IDs of personas selected at runtime (controlled by parent)
  runtimeSelectedIds: number[];
  // Callback when runtime selection changes
  onRuntimeSelectionChange: (ids: number[]) => void;
  // Whether the popover trigger is disabled
  disabled?: boolean;
}

export default function CallableAgentsPopover({
  currentPersonaId,
  preConfiguredCallableIds,
  runtimeSelectedIds,
  onRuntimeSelectionChange,
  disabled = false,
}: CallableAgentsPopoverProps) {
  const { agents, isLoading } = useAgents();
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Filter agents to show only non-builtin, non-current agents
  const availableAgents = useMemo(() => {
    return agents.filter(
      (agent) =>
        !agent.builtin_persona &&
        agent.id !== currentPersonaId &&
        agent.id !== 0
    );
  }, [agents, currentPersonaId]);

  // Filter by search query
  const filteredAgents = useMemo(() => {
    if (!searchQuery.trim()) {
      return availableAgents;
    }
    const query = searchQuery.toLowerCase();
    return availableAgents.filter(
      (agent) =>
        agent.name.toLowerCase().includes(query) ||
        agent.description?.toLowerCase().includes(query)
    );
  }, [availableAgents, searchQuery]);

  // Count of selected agents (pre-configured + runtime)
  const totalSelectedCount = useMemo(() => {
    const preConfiguredSet = new Set(preConfiguredCallableIds);
    const runtimeSet = new Set(runtimeSelectedIds);
    // Merge and dedupe
    const combined = new Set([...preConfiguredSet, ...runtimeSet]);
    return combined.size;
  }, [preConfiguredCallableIds, runtimeSelectedIds]);

  // Handle toggle for runtime selection
  const handleToggle = useCallback(
    (agentId: number) => {
      if (runtimeSelectedIds.includes(agentId)) {
        onRuntimeSelectionChange(
          runtimeSelectedIds.filter((id) => id !== agentId)
        );
      } else {
        onRuntimeSelectionChange([...runtimeSelectedIds, agentId]);
      }
    },
    [runtimeSelectedIds, onRuntimeSelectionChange]
  );

  // Reset search when popover closes
  const handleOpenChange = useCallback((newOpen: boolean) => {
    setOpen(newOpen);
    if (!newOpen) {
      setSearchQuery("");
    }
  }, []);

  const renderAgentItem = (agent: MinimalPersonaSnapshot) => {
    const isPreConfigured = preConfiguredCallableIds.includes(agent.id);
    const isRuntimeSelected = runtimeSelectedIds.includes(agent.id);

    return (
      <div
        key={agent.id}
        className="flex flex-row w-full items-center p-2 rounded-08 gap-2 hover:bg-background-tint-02"
      >
        {/* Avatar */}
        <div className="flex flex-col justify-center items-center h-[1rem] min-w-[1rem]">
          <CustomAgentAvatar
            size={20}
            iconName={agent.icon_name ?? undefined}
            src={
              agent.uploaded_image_id
                ? `/api/chat/file/${agent.uploaded_image_id}`
                : undefined
            }
            name={agent.name}
          />
        </div>

        {/* Name and description */}
        <div className="flex-1 min-w-0">
          <Truncated mainUiMuted className="text-left w-full">
            {agent.name}
          </Truncated>
          {agent.description && (
            <Truncated secondaryBody text03 className="text-left w-full">
              {agent.description}
            </Truncated>
          )}
        </div>

        {/* Right control: checkmark or switch */}
        <div className="shrink-0">
          {isPreConfigured ? (
            // Pre-configured: show grey checkmark (non-interactive)
            <SvgCheck className="h-4 w-4 stroke-text-04" />
          ) : (
            // Runtime selectable: show switch
            <Switch
              checked={isRuntimeSelected}
              onCheckedChange={() => handleToggle(agent.id)}
              aria-label={`Toggle ${agent.name}`}
            />
          )}
        </div>
      </div>
    );
  };

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <Popover.Trigger asChild disabled={disabled}>
        <div>
          <SelectButton
            leftIcon={SvgOnyxOctagon}
            onClick={() => setOpen(true)}
            transient={open}
            rightChevronIcon
            disabled={disabled}
            badge={totalSelectedCount > 0 ? totalSelectedCount : undefined}
          >
            Sub-Agents
          </SelectButton>
        </div>
      </Popover.Trigger>
      <Popover.Content side="bottom" align="start" width="lg">
        <Section gap={0.5}>
          {/* Search Input */}
          <InputTypeIn
            leftSearchIcon
            variant="internal"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search agents..."
          />

          {/* Agent List - constrained height to fit in viewport */}
          <div className="flex flex-col gap-1 max-h-[12rem] overflow-y-auto">
            {isLoading ? (
              <div className="py-3">
                <Text secondaryBody text03>
                  Loading agents...
                </Text>
              </div>
            ) : filteredAgents.length === 0 ? (
              <div className="py-3">
                <Text secondaryBody text03>
                  {searchQuery ? "No agents found" : "No agents available"}
                </Text>
              </div>
            ) : (
              <>
                {/* Show pre-configured agents first (with grey checkmark) */}
                {filteredAgents
                  .filter((a) => preConfiguredCallableIds.includes(a.id))
                  .map(renderAgentItem)}
                {/* Then show other agents (with switches) */}
                {filteredAgents
                  .filter((a) => !preConfiguredCallableIds.includes(a.id))
                  .map(renderAgentItem)}
              </>
            )}
          </div>

          {/* Helper text */}
          <div className="px-2 pb-1">
            <Text text04 secondaryBody>
              {preConfiguredCallableIds.length > 0
                ? `${preConfiguredCallableIds.length} agent(s) pre-configured. Select more agents to call during this chat.`
                : "Select agents this assistant can delegate tasks to."}
            </Text>
          </div>
        </Section>
      </Popover.Content>
    </Popover>
  );
}
