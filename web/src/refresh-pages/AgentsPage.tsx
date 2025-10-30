"use client";

import React, { useMemo, useState } from "react";
import AgentCard from "@/refresh-components/AgentCard";
import { useUser } from "@/components/user/UserProvider";
import { checkUserOwnsAssistant as checkUserOwnsAgent } from "@/lib/assistants/checkOwnership";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import Text from "@/refresh-components/texts/Text";
import SvgFilter from "@/icons/filter";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PageHeader from "@/refresh-components/page-components/PageHeader";
import SvgOnyxOctagon from "@/icons/onyx-octagon";
import PageWrapper from "@/refresh-components/page-components/PageWrapper";

interface AgentsSectionProps {
  title: string;
  agents: MinimalPersonaSnapshot[];
}

function AgentsSection({ title, agents }: AgentsSectionProps) {
  if (agents.length === 0) return null;

  return (
    <div className="py-6 flex flex-col gap-4">
      <Text headingH2>{title}</Text>
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

function useAgentFilters() {
  const [agentFilters, setAgentFilters] = useState<
    Record<AgentFilter, boolean>
  >({
    [AgentFilter.Pinned]: false,
    [AgentFilter.Public]: false,
    [AgentFilter.Private]: false,
    [AgentFilter.Mine]: false,
  });

  function toggleAgentFilter(filter: AgentFilter) {
    setAgentFilters((prevFilters) => ({
      ...prevFilters,
      [filter]: !prevFilters[filter],
    }));
  }

  return { agentFilters, toggleAgentFilter };
}

export default function AgentsPage() {
  const { agents, pinnedAgents } = useAgentsContext();
  const { agentFilters, toggleAgentFilter } = useAgentFilters();
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
      const publicFilter = !agentFilters[AgentFilter.Public] || agent.is_public;
      const privateFilter =
        !agentFilters[AgentFilter.Private] || !agent.is_public;
      const pinnedFilter =
        !agentFilters[AgentFilter.Pinned] ||
        (pinnedAgents.map((a) => a.id).includes(agent.id) ?? false);

      const mineFilter =
        !agentFilters[AgentFilter.Mine] || checkUserOwnsAgent(user, agent);

      const isNotUnifiedAgent = agent.id !== 0;

      return (
        (nameMatches || labelMatches) &&
        publicFilter &&
        privateFilter &&
        pinnedFilter &&
        mineFilter &&
        isNotUnifiedAgent
      );
    });
  }, [agents, searchQuery, agentFilters, pinnedAgents, user]);

  const featuredAgents = [
    ...memoizedCurrentlyVisibleAgents.filter(
      (agent) => agent.is_default_persona
    ),
  ];
  const allAgents = memoizedCurrentlyVisibleAgents.filter(
    (agent) => !agent.is_default_persona
  );

  return (
    <PageWrapper
      data-testid="AgentsPage/container"
      aria-label="Agents Page"
      className="w-full"
    >
      <PageHeader
        icon={SvgOnyxOctagon}
        title="Agents"
        description="Browse and manage your AI agents"
        sticky
        rightChildren={<Button href="/assistants/new">Create</Button>}
      >
        {/* Search Section */}
        {/*<div className="flex flex-row items-center gap-2">
          <InputTypeIn
            placeholder="Search..."
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
        </div>*/}

        {/* Filters Section */}
        {/*<div className="flex items-center gap-2 flex-wrap">
          <SvgFilter className="w-[1.2rem] h-[1.2rem] stroke-text-05" />
          <AgentBadgeSelector
            text="Pinned"
            selected={agentFilters[AgentFilter.Pinned]}
            toggleFilter={() => toggleAgentFilter(AgentFilter.Pinned)}
          />

          <AgentBadgeSelector
            text="Mine"
            selected={agentFilters[AgentFilter.Mine]}
            toggleFilter={() => toggleAgentFilter(AgentFilter.Mine)}
          />
          <AgentBadgeSelector
            text="Private"
            selected={agentFilters[AgentFilter.Private]}
            toggleFilter={() => toggleAgentFilter(AgentFilter.Private)}
          />
          <AgentBadgeSelector
            text="Public"
            selected={agentFilters[AgentFilter.Public]}
            toggleFilter={() => toggleAgentFilter(AgentFilter.Public)}
          />
        </div>*/}
      </PageHeader>

      {/* Agents List */}
      {/*<div className="mt-4">
        {featuredAgents.length === 0 && allAgents.length === 0 ? (
          <Text className="w-full h-full flex flex-col items-center justify-center py-12">
            No Agents configured yet...
          </Text>
        ) : (
          <>
            <AgentsSection title="Featured Agents" agents={featuredAgents} />
            <AgentsSection title="All Agents" agents={allAgents} />
          </>
        )}
      </div>*/}
    </PageWrapper>
  );
}
