import React, { useEffect, useMemo, useState } from "react";
import {
  InputTypeIn,
  LineItemButton,
  Popover,
  PopoverMenu,
  SelectButton,
  Text,
} from "@opal/components";
import { SvgOnyxOctagon } from "@opal/icons";
import { Section } from "@opal/layouts";
import {
  usePersonaMessages,
  usePersonaUniqueUsers,
} from "@/app/ee/admin/performance/lib";
import {
  AnalyticsChart,
  chartSeries,
} from "@/app/ee/admin/performance/usage/AnalyticsChart";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
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
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const matches = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (query === "") return agents;
    return agents.filter((agent) => agent.name.toLowerCase().includes(query));
  }, [agents, search]);

  return (
    <Popover
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) setSearch("");
      }}
    >
      <Popover.Trigger asChild>
        <SelectButton
          icon={SvgOnyxOctagon}
          state="empty"
          variant="select-input"
        >
          {selectedAgent?.name ?? "Select an agent to display"}
        </SelectButton>
      </Popover.Trigger>
      <Popover.Content align="start">
        <PopoverMenu>
          {[
            <InputTypeIn
              key="agent-search"
              placeholder="Search agents..."
              variant="internal"
              searchIcon
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />,
            ...matches.map((agent) => (
              <Popover.Close asChild key={agent.id}>
                <LineItemButton
                  sizePreset="main-ui"
                  rounding="sm"
                  selectVariant="select-heavy"
                  icon={SvgOnyxOctagon}
                  title={agent.name}
                  state={selectedAgent?.id === agent.id ? "selected" : "empty"}
                  onClick={() => onSelect(agent.id)}
                />
              </Popover.Close>
            )),
            ...(matches.length === 0
              ? [
                  <Section
                    key="no-matches"
                    flexDirection="row"
                    justifyContent="center"
                    alignItems="center"
                    padding={0.5}
                    width="full"
                    height="fit"
                  >
                    <Text font="secondary-body" color="text-03">
                      No agents match that search
                    </Text>
                  </Section>,
                ]
              : []),
          ]}
        </PopoverMenu>
      </Popover.Content>
    </Popover>
  );
}

interface PersonaMessagesChartProps {
  availablePersonas: Agent[];
  agentsError?: Error;
  agentsLoading?: boolean;
  timeRange: DateRangePickerValue;
}

export function PersonaMessagesChart({
  availablePersonas,
  agentsError,
  agentsLoading,
  timeRange,
}: PersonaMessagesChartProps) {
  const [selectedPersonaId, setSelectedPersonaId] = useState<
    number | undefined
  >(undefined);

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

  const agents = availablePersonas ?? [];
  const selectedAgent = agents.find((agent) => agent.id === selectedPersonaId);

  return (
    <AnalyticsChart
      title="Agent Analytics"
      description="Messages and unique users per day for the selected agent"
      timeRange={timeRange}
      isLoading={
        agentsLoading || isPersonaMessagesLoading || isPersonaUniqueUsersLoading
      }
      error={agentsError || personaMessagesError || personaUniqueUsersError}
      errorMessage="Failed to fetch agent data..."
      emptyMessage="No data found for selected agent in the specified time range"
      {...(selectedPersonaId === undefined && {
        prompt: "Select an agent to view analytics",
      })}
      headerChildren={
        <Section
          flexDirection="row"
          justifyContent="start"
          alignItems="center"
          width="full"
          height="fit"
        >
          <PersonaPicker
            agents={agents}
            selectedAgent={selectedAgent}
            onSelect={setSelectedPersonaId}
          />
        </Section>
      }
      series={[
        chartSeries(
          "Messages",
          personaMessagesData,
          (entry) => entry.total_messages
        ),
        chartSeries(
          "Unique Users",
          personaUniqueUsersData,
          (entry) => entry.unique_users
        ),
      ]}
    />
  );
}
