"use client";

import { useMemo, useState, useRef } from "react";
import AgentCard from "@/sections/agents/AgentCard";
import { useUser } from "@/providers/UserProvider";
import { checkUserOwnsAgent as checkUserOwnsAgent } from "@/lib/agents";
import { useAgents } from "@/hooks/useAgents";
import { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import TextSeparator from "@/refresh-components/TextSeparator";
import Tabs from "@/refresh-components/Tabs";
import { Button } from "@opal/components";
import { SvgOnyxOctagon, SvgPlus } from "@opal/icons";
import useOnMount from "@/hooks/useOnMount";
import { useAgentsFilters } from "@/sections/agents/AgentsFilters";

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
        <Text as="p" headingH3>
          {title}
        </Text>
        <Text as="p" secondaryBody text03>
          {description}
        </Text>
      </div>
      <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-2">
        {agents
          .sort((a, b) => b.id - a.id)
          .map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
      </div>
    </div>
  );
}

export default function AgentsNavigationPage() {
  const { agents } = useAgents();
  const { user } = useUser();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"all" | "your">("all");
  const searchInputRef = useRef<HTMLInputElement>(null);

  useOnMount(() => {
    searchInputRef.current?.focus();
  });

  const nonBuiltinAgents = useMemo(
    () => agents.filter((a) => !a.builtin_persona),
    [agents]
  );

  const { filtered: agentsFilteredByFilters, filterBar } =
    useAgentsFilters(nonBuiltinAgents);

  const memoizedCurrentlyVisibleAgents = useMemo(() => {
    return agentsFilteredByFilters.filter((agent) => {
      const nameMatches = agent.name
        .toLowerCase()
        .includes(searchQuery.toLowerCase());
      const labelMatches = agent.labels?.some((label) =>
        label.name.toLowerCase().includes(searchQuery.toLowerCase())
      );

      const mineFilter =
        activeTab === "your" ? checkUserOwnsAgent(user, agent) : true;

      return (nameMatches || labelMatches) && mineFilter;
    });
  }, [agentsFilteredByFilters, searchQuery, activeTab, user]);

  const featuredAgents = [
    ...memoizedCurrentlyVisibleAgents.filter((agent) => agent.is_featured),
  ];
  const allAgents = memoizedCurrentlyVisibleAgents.filter(
    (agent) => !agent.is_featured
  );

  const agentCount = featuredAgents.length + allAgents.length;

  return (
    <SettingsLayouts.Root
      data-testid="AgentsPage/container"
      aria-label="Agents Page"
    >
      <SettingsLayouts.Header
        icon={SvgOnyxOctagon}
        title="Agents"
        description="Customize AI behavior and knowledge for you and your team's use cases."
        rightChildren={
          <Button
            href="/app/agents/create"
            icon={SvgPlus}
            aria-label="AgentsPage/new-agent-button"
          >
            New Agent
          </Button>
        }
      >
        <div className="flex flex-col gap-2">
          <div className="flex flex-row items-center gap-2">
            <div className="flex-[2]">
              <InputTypeIn
                ref={searchInputRef}
                placeholder="Search agents..."
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                leftSearchIcon
              />
            </div>
            <div className="flex-1">
              <Tabs
                value={activeTab}
                onValueChange={(value) => setActiveTab(value as "all" | "your")}
              >
                <Tabs.List>
                  <Tabs.Trigger value="all">All Agents</Tabs.Trigger>
                  <Tabs.Trigger value="your">Your Agents</Tabs.Trigger>
                </Tabs.List>
              </Tabs>
            </div>
          </div>
          <div className="flex flex-row gap-2">{filterBar}</div>
        </div>
      </SettingsLayouts.Header>

      {/* Agents List */}
      <SettingsLayouts.Body>
        {agentCount === 0 ? (
          <Text
            as="p"
            className="w-full h-full flex flex-col items-center justify-center py-12"
            text03
          >
            No Agents found
          </Text>
        ) : (
          <>
            <AgentsSection
              title="Featured Agents"
              description="Curated by your team"
              agents={featuredAgents}
            />
            <AgentsSection title="All Agents" agents={allAgents} />
            <TextSeparator
              count={agentCount}
              text={agentCount === 1 ? "Agent" : "Agents"}
            />
          </>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
