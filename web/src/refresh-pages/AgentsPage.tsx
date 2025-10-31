"use client";

import React, { useMemo, useState, useRef, useEffect } from "react";
import AgentCard from "@/refresh-components/AgentCard";
import { useUser } from "@/components/user/UserProvider";
import { checkUserOwnsAssistant as checkUserOwnsAgent } from "@/lib/assistants/checkOwnership";
import { useAgentsContext } from "@/refresh-components/contexts/AgentsContext";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PageHeader from "@/refresh-components/page-components/PageHeader";
import SvgOnyxOctagon from "@/icons/onyx-octagon";
import PageWrapper from "@/refresh-components/page-components/PageWrapper";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import CounterSeparator from "@/refresh-components/CounterSeparator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import SvgUser from "@/icons/user";
import SvgCheck from "@/icons/check";
import FilterButton from "@/refresh-components/buttons/FilterButton";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import LineItem from "@/refresh-components/buttons/LineItem";

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
      <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-2">
        {agents
          .sort((a, b) => b.id - a.id)
          .map((agent, index) => (
            <AgentCard key={index} agent={agent} />
          ))}
      </div>
    </div>
  );
}

export default function AgentsPage() {
  const { agents } = useAgentsContext();
  // const { agentFilters, toggleAgentFilter } = useAgentFilters();
  const [open, setOpen] = useState(false);
  const { user } = useUser();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"all" | "mine">("all");
  const [selectedCreatorIds, setSelectedCreatorIds] = useState<Set<string>>(
    new Set()
  );
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Focus the search input when the page loads
    searchInputRef.current?.focus();
  }, []);

  const uniqueCreators = useMemo(() => {
    const creatorsMap = new Map<string, { id: string; email: string }>();
    agents.forEach((agent) => {
      if (agent.owner) {
        creatorsMap.set(agent.owner.id, agent.owner);
      }
    });
    return Array.from(creatorsMap.values()).sort((a, b) =>
      a.email.localeCompare(b.email)
    );
  }, [agents]);

  const memoizedCurrentlyVisibleAgents = useMemo(() => {
    return agents.filter((agent) => {
      const nameMatches = agent.name
        .toLowerCase()
        .includes(searchQuery.toLowerCase());
      const labelMatches = agent.labels?.some((label) =>
        label.name.toLowerCase().includes(searchQuery.toLowerCase())
      );

      const mineFilter =
        activeTab === "mine" ? checkUserOwnsAgent(user, agent) : true;
      const isNotUnifiedAgent = agent.id !== 0;

      const creatorFilter =
        selectedCreatorIds.size === 0 ||
        (agent.owner && selectedCreatorIds.has(agent.owner.id));

      return (
        (nameMatches || labelMatches) &&
        mineFilter &&
        isNotUnifiedAgent &&
        creatorFilter
      );
    });
  }, [agents, searchQuery, activeTab, user, selectedCreatorIds]);

  const featuredAgents = [
    ...memoizedCurrentlyVisibleAgents.filter(
      (agent) => agent.is_default_persona
    ),
  ];
  const allAgents = memoizedCurrentlyVisibleAgents.filter(
    (agent) => !agent.is_default_persona
  );

  const agentCount = featuredAgents.length + allAgents.length;

  const filterButtonText = useMemo(() => {
    if (selectedCreatorIds.size === 0) {
      return "Everyone";
    } else if (selectedCreatorIds.size === 1) {
      const selectedId = Array.from(selectedCreatorIds)[0];
      const creator = uniqueCreators.find((c) => c.id === selectedId);
      return creator?.email || "Everyone";
    } else {
      return `${selectedCreatorIds.size} selected`;
    }
  }, [selectedCreatorIds, uniqueCreators]);

  return (
    <PageWrapper data-testid="AgentsPage/container" aria-label="Agents Page">
      <PageHeader
        icon={SvgOnyxOctagon}
        title="Agents & Assistants"
        description="Customize AI behavior and knowledge for you and your team’s use cases."
        sticky
        className="bg-background-tint-01"
        rightChildren={
          <CreateButton primary secondary={undefined} href="/assistants/new">
            New Agent
          </CreateButton>
        }
      >
        <div className="flex flex-col gap-2">
          <div className="flex flex-row items-center gap-2">
            <InputTypeIn
              ref={searchInputRef}
              placeholder="Search agents..."
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              leftSearchIcon
            />
            <Tabs
              value={activeTab}
              onValueChange={(value) => setActiveTab(value as "all" | "mine")}
            >
              <TabsList>
                <TabsTrigger value="all">All Agents</TabsTrigger>
                <TabsTrigger value="mine">My Agents</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <div className="flex flex-row gap-2">
            <Popover open={open} onOpenChange={setOpen}>
              <PopoverTrigger asChild>
                <FilterButton
                  leftIcon={SvgUser}
                  open={selectedCreatorIds.size > 0}
                  onClear={() => setSelectedCreatorIds(new Set())}
                >
                  {filterButtonText}
                </FilterButton>
              </PopoverTrigger>
              <PopoverContent align="start">
                <PopoverMenu medium>
                  {[
                    <InputTypeIn
                      key="created-by"
                      placeholder="Created by..."
                      internal
                      leftSearchIcon
                    />,
                    ...uniqueCreators.map((creator) => {
                      const isSelected = selectedCreatorIds.has(creator.id);
                      return (
                        <LineItem
                          key={creator.id}
                          icon={isSelected ? SvgCheck : SvgUser}
                          forced={isSelected}
                          onClick={() => {
                            setSelectedCreatorIds((prev) => {
                              const newSet = new Set(prev);
                              if (newSet.has(creator.id)) {
                                newSet.delete(creator.id);
                              } else {
                                newSet.add(creator.id);
                              }
                              return newSet;
                            });
                          }}
                        >
                          {creator.email}
                        </LineItem>
                      );
                    }),
                  ]}
                </PopoverMenu>
              </PopoverContent>
            </Popover>
          </div>
        </div>
      </PageHeader>

      {/* Agents List */}
      <div className="p-4 flex flex-col gap-8">
        {agentCount === 0 ? (
          <Text
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
