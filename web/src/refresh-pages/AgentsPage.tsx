"use client";

import React, { useMemo, useState } from "react";
import AgentCard from "@/refresh-components/AgentCard";
import { useUser } from "@/components/user/UserProvider";
import { checkUserOwnsAssistant as checkUserOwnsAgent } from "@/lib/assistants/checkOwnership";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PageHeader from "@/refresh-components/page-components/PageHeader";
import SvgOnyxOctagon from "@/icons/onyx-octagon";
import PageWrapper from "@/refresh-components/page-components/PageWrapper";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import CounterSeparator from "@/refresh-components/CounterSeparator";

interface AgentsSectionProps {
  title: string;
  description?: string;
  agents: MinimalPersonaSnapshot[];
}

function AgentsSection({ title, description, agents }: AgentsSectionProps) {
  if (agents.length === 0) return null;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Text headingH3>{title}</Text>
        <Text secondaryBody text03>
          {description}
        </Text>
      </div>
      <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-4">
        {agents
          .sort((a, b) => b.id - a.id)
          .map((agent, index) => (
            <AgentCard key={index} agent={agent} />
          ))}
      </div>
    </div>
  );
}

interface AgentBadgeSelectorProps {
  text: string;
  selected: boolean;
  toggleFilter: () => void;
}

function AgentBadgeSelector({
  text,
  selected,
  toggleFilter,
}: AgentBadgeSelectorProps) {
  return (
    <Button secondary transient={selected} onClick={toggleFilter}>
      {text}
    </Button>
  );
}

export enum AgentFilter {
  Pinned = "Pinned",
  Public = "Public",
  Private = "Private",
  Mine = "Mine",
}

// function useAgentFilters() {
//   const [agentFilters, setAgentFilters] = useState<
//     Record<AgentFilter, boolean>
//   >({
//     [AgentFilter.Pinned]: false,
//     [AgentFilter.Public]: false,
//     [AgentFilter.Private]: false,
//     [AgentFilter.Mine]: false,
//   });
//   function toggleAgentFilter(filter: AgentFilter) {
//     setAgentFilters((prevFilters) => ({
//       ...prevFilters,
//       [filter]: !prevFilters[filter],
//     }));
//   }
//   return { agentFilters, toggleAgentFilter };
// }

export default function AgentsPage() {
  const { agents, pinnedAgents } = useAgentsContext();
  // const { agentFilters, toggleAgentFilter } = useAgentFilters();
  const { user } = useUser();
  const [searchQuery, setSearchQuery] = useState("");

  const memoizedCurrentlyVisibleAgents = useMemo(() => {
    return agents.filter((agent) => {
      const nameMatches = agent.name
        .toLowerCase()
        .includes(searchQuery.toLowerCase());
      const labelMatches = agent.labels?.some((label) =>
        label.name.toLowerCase().includes(searchQuery.toLowerCase())
      );
      // const publicFilter = !agentFilters[AgentFilter.Public] || agent.is_public;
      // const privateFilter =
      //   !agentFilters[AgentFilter.Private] || !agent.is_public;
      // const pinnedFilter =
      //   !agentFilters[AgentFilter.Pinned] ||
      //   (pinnedAgents.map((a) => a.id).includes(agent.id) ?? false);

      // const mineFilter =
      //   !agentFilters[AgentFilter.Mine] || checkUserOwnsAgent(user, agent);

      const isNotUnifiedAgent = agent.id !== 0;

      return (
        (nameMatches || labelMatches) &&
        // publicFilter &&
        // privateFilter &&
        // pinnedFilter &&
        // mineFilter &&
        isNotUnifiedAgent
      );
    });
  }, [
    agents,
    searchQuery,
    // agentFilters,
    pinnedAgents,
    user,
  ]);

  const featuredAgents = [
    ...memoizedCurrentlyVisibleAgents.filter(
      (agent) => agent.is_default_persona
    ),
  ];
  const allAgents = memoizedCurrentlyVisibleAgents.filter(
    (agent) => !agent.is_default_persona
  );

  const agentCount = featuredAgents.length + allAgents.length;

  return (
    <PageWrapper data-testid="AgentsPage/container" aria-label="Agents Page">
      <PageHeader
        icon={SvgOnyxOctagon}
        title="Agents & Assistants"
        description="Customize AI behavior and knowledge for you and your team’s use cases."
        sticky
        rightChildren={
          <CreateButton primary secondary={undefined}>
            New Agent
          </CreateButton>
        }
      >
        <div className="flex flex-row gap-2">
          <InputTypeIn
            placeholder="Search agents..."
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            leftSearchIcon
          />
        </div>
      </PageHeader>

      {/* Agents List */}

      <div className="p-4 flex flex-col gap-8">
        {agentCount === 0 ? (
          <Text className="w-full h-full flex flex-col items-center justify-center py-12">
            No Agents configured yet...
          </Text>
        ) : (
          <>
            <AgentsSection
              title="Featured Agents"
              description="Curated by your team"
              agents={featuredAgents}
            />
            <AgentsSection title="All Agents" agents={allAgents} />
            <CounterSeparator
              count={agentCount}
              text={agentCount === 1 ? "Agent" : "Agents"}
            />
          </>
        )}
      </div>
    </PageWrapper>
  );
}
