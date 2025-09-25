"use client";

import React, { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AgentCard from "@/sections/AgentsModal/AgentCard";
import { useUser } from "@/components/user/UserProvider";
import { checkUserOwnsAssistant as checkUserOwnsAgent } from "@/lib/assistants/checkOwnership";
import { useAgentsContext } from "@/components-2/context/AgentsContext";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import Text from "@/components-2/Text";
import Modal from "@/components-2/modals/Modal";
import { ModalIds, useModal } from "@/components-2/context/ModalContext";
import SvgFilter from "@/icons/filter";

interface AgentsSectionProps {
  title: string;
  agents: MinimalPersonaSnapshot[];
  pinnedAgents: MinimalPersonaSnapshot[];
}

function AgentsSection({ title, agents, pinnedAgents }: AgentsSectionProps) {
  const { toggleModal } = useModal();

  if (agents.length === 0) {
    return null;
  }

  return (
    <div className="py-padding-content flex flex-col gap-spacing-paragraph">
      <Text headingH2>{title}</Text>
      <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-spacing-paragraph">
        {agents
          .sort((a, b) => b.id - a.id)
          .map((agent, index) => (
            <AgentCard
              key={index}
              pinned={pinnedAgents.map((a) => a.id).includes(agent.id)}
              agent={agent}
              closeModal={() => toggleModal(ModalIds.AgentsModal, false)}
            />
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
    <div
      className={`bg-background-tint-03 hover:bg-background-tint-02 ${selected && "!bg-action-link-05 hover:!bg-action-link-04"} border p-spacing-interline rounded-08`}
      onClick={toggleFilter}
    >
      <Text secondaryBody>{text}</Text>
    </div>
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

export default function AgentsModal() {
  const { agents, pinnedAgents } = useAgentsContext();
  const { agentFilters, toggleAgentFilter } = useAgentFilters();
  const router = useRouter();
  const { user } = useUser();
  const [searchQuery, setSearchQuery] = useState("");
  const { toggleModal } = useModal();

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
  }, [agents, searchQuery, agentFilters]);

  const featuredAgents = [
    ...memoizedCurrentlyVisibleAgents.filter(
      (agent) => agent.is_default_persona
    ),
  ];
  const allAgents = memoizedCurrentlyVisibleAgents.filter(
    (agent) => !agent.is_default_persona
  );

  return (
    <Modal id={ModalIds.AgentsModal} title="Agents" mini>
      <div className="flex flex-col sticky top-[0rem] z-10 bg-background-tint-01">
        <div className="flex flex-row items-center gap-spacing-interline">
          <input
            className="w-full h-[3rem] border bg-transparent rounded-08 p-padding-button"
            placeholder="Search..."
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
          <button
            onClick={() => {
              toggleModal(ModalIds.AgentsModal, false);
              router.push("/assistants/new");
            }}
            className="p-padding-button bg-background-tint-03 rounded-08 hover:bg-background-tint-02"
          >
            <Text>Create</Text>
          </button>
        </div>

        <div className="py-padding-content flex items-center gap-spacing-interline flex-wrap">
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
        </div>
      </div>

      <div className="h-full w-full">
        {featuredAgents.length === 0 && allAgents.length === 0 ? (
          <Text
            mainBody
            className="w-full h-full flex flex-col items-center justify-center"
          >
            No Agents configured yet...
          </Text>
        ) : (
          <>
            <AgentsSection
              title="Featured Agents"
              agents={featuredAgents}
              pinnedAgents={pinnedAgents}
            />
            <AgentsSection
              title="All Agents"
              agents={allAgents}
              pinnedAgents={pinnedAgents}
            />
          </>
        )}
      </div>
    </Modal>
  );
}
