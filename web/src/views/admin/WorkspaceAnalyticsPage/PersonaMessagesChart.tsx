import React, { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Dropdown, SelectButton } from "@opal/components";
import { SvgOnyxOctagon } from "@opal/icons";
import { Section } from "@opal/layouts";
import { usePersonaMessages, usePersonaUniqueUsers } from "@/lib/usage/hooks";
import { useAdminAgents } from "@/lib/agents/hooks";
import {
  AnalyticsChart,
  chartSeries,
  resolveChartState,
} from "@/sections/usage/AnalyticsChart";
import { InputDateRangePickerValue } from "@opal/components";
import { Agent } from "@/lib/agents/types";

interface PersonaPickerProps {
  agents: Agent[];
  selectedAgent: Agent | undefined;
  onSelect: (agentId: number) => void;
}

function PersonaPicker({
  agents,
  selectedAgent,
  onSelect,
}: PersonaPickerProps) {
  const t = useTranslations("admin.analytics");
  const [open, setOpen] = useState(false);

  return (
    <Dropdown open={open} onOpenChange={setOpen}>
      <Dropdown.Trigger asChild>
        <SelectButton
          icon={SvgOnyxOctagon}
          state="empty"
          variant="select-input"
        >
          {selectedAgent?.name ?? t("agentPicker.placeholder")}
        </SelectButton>
      </Dropdown.Trigger>
      <Dropdown.Data
        label={t("agentPicker.placeholder")}
        search={{ placeholder: t("agentPicker.search.placeholder") }}
        noMatchText={t("agentPicker.empty.label")}
        value={selectedAgent ? String(selectedAgent.id) : ""}
        onSelect={(option) => {
          const agent = agents.find((a) => String(a.id) === option.value);
          if (agent) onSelect(agent.id);
        }}
        items={agents.map((agent) => ({
          kind: "option",
          value: String(agent.id),
          icon: SvgOnyxOctagon,
          title: agent.name,
        }))}
      />
    </Dropdown>
  );
}

interface PersonaMessagesChartProps {
  timeRange: InputDateRangePickerValue;
}

export function PersonaMessagesChart({ timeRange }: PersonaMessagesChartProps) {
  const t = useTranslations("admin.analytics");
  const [selectedPersonaId, setSelectedPersonaId] = useState<
    number | undefined
  >(undefined);

  const {
    agents,
    error: agentsError,
    isLoading: agentsLoading,
  } = useAdminAgents();

  const {
    data: personaMessagesData,
    isLoading: isPersonaMessagesLoading,
    error: personaMessagesError,
  } = usePersonaMessages(selectedPersonaId, timeRange);

  const {
    data: personaUniqueUsersData,
    isLoading: isPersonaUniqueUsersLoading,
    error: personaUniqueUsersError,
  } = usePersonaUniqueUsers(selectedPersonaId, timeRange);

  useEffect(() => {
    if (agentsError) {
      console.error("Failed to fetch admin agents:", agentsError);
    }
    if (personaMessagesError) {
      console.error("Failed to fetch agent messages:", personaMessagesError);
    }
    if (personaUniqueUsersError) {
      console.error(
        "Failed to fetch agent unique users:",
        personaUniqueUsersError
      );
    }
  }, [agentsError, personaMessagesError, personaUniqueUsersError]);

  const selectedAgent = agents.find((agent) => agent.id === selectedPersonaId);

  const series = [
    chartSeries(
      t("agentChart.series.messages.label"),
      personaMessagesData,
      (entry) => entry.total_messages
    ),
    chartSeries(
      t("agentChart.series.uniqueUsers.label"),
      personaUniqueUsersData,
      (entry) => entry.unique_users
    ),
  ];

  return (
    <AnalyticsChart
      title={t("agentChart.title")}
      description={t("agentChart.description")}
      timeRange={timeRange}
      state={
        // The picker is only usable once the agent list resolves, so its
        // loading and error states outrank the "pick an agent" prompt.
        selectedPersonaId === undefined && !agentsLoading && !agentsError
          ? { status: "empty", message: t("agentChart.selectPrompt") }
          : resolveChartState({
              isLoading:
                agentsLoading ||
                isPersonaMessagesLoading ||
                isPersonaUniqueUsersLoading,
              error:
                agentsError || personaMessagesError || personaUniqueUsersError,
              errorMessage: t("agentChart.error"),
              emptyMessage: t("agentChart.empty"),
              series,
            })
      }
      headerChildren={
        <PersonaPicker
          agents={agents}
          selectedAgent={selectedAgent}
          onSelect={setSelectedPersonaId}
        />
      }
    />
  );
}
