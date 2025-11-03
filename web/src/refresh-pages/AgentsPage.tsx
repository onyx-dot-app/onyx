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
import CounterSeparator from "@/refresh-components/CounterSeparator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import SvgUser from "@/icons/user";
import SvgCheck from "@/icons/check";
import FilterButton from "@/refresh-components/buttons/FilterButton";
import SvgActions from "@/icons/actions";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import Button from "@/refresh-components/buttons/Button";
import SvgPlus from "@/icons/plus";
import {
  SEARCH_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
  SYSTEM_TOOL_ICONS,
} from "@/app/chat/components/tools/constants";

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
          .map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
      </div>
    </div>
  );
}

export default function AgentsPage() {
  const { agents } = useAgentsContext();
  const [creatorFilterOpen, setCreatorFilterOpen] = useState(false);
  const [actionsFilterOpen, setActionsFilterOpen] = useState(false);
  const { user } = useUser();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"all" | "your">("all");
  const [selectedCreatorIds, setSelectedCreatorIds] = useState<Set<string>>(
    new Set()
  );
  const [selectedActionIds, setSelectedActionIds] = useState<Set<number>>(
    new Set()
  );
  const [creatorSearchQuery, setCreatorSearchQuery] = useState("");
  const [actionsSearchQuery, setActionsSearchQuery] = useState("");
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

    let creators = Array.from(creatorsMap.values()).sort((a, b) =>
      a.email.localeCompare(b.email)
    );

    // Add current user if not in the list, and put them first
    if (user) {
      const hasCurrentUser = creators.some((c) => c.id === user.id);

      if (!hasCurrentUser) {
        creators = [{ id: user.id, email: user.email }, ...creators];
      } else {
        // Sort to put current user first
        creators = creators.sort((a, b) => {
          if (a.id === user.id) return -1;
          if (b.id === user.id) return 1;
          return 0;
        });
      }
    }

    return creators;
  }, [agents, user]);

  const filteredCreators = useMemo(() => {
    if (!creatorSearchQuery) return uniqueCreators;

    return uniqueCreators.filter((creator) =>
      creator.email.toLowerCase().includes(creatorSearchQuery.toLowerCase())
    );
  }, [uniqueCreators, creatorSearchQuery]);

  const uniqueActions = useMemo(() => {
    const actionsMap = new Map<
      number,
      { id: number; name: string; display_name: string }
    >();
    agents.forEach((agent) => {
      agent.tools.forEach((tool) => {
        actionsMap.set(tool.id, {
          id: tool.id,
          name: tool.name,
          display_name: tool.display_name,
        });
      });
    });

    const systemToolIds = [
      SEARCH_TOOL_ID,
      IMAGE_GENERATION_TOOL_ID,
      WEB_SEARCH_TOOL_ID,
    ];

    const allActions = Array.from(actionsMap.values());
    const systemTools = allActions.filter((action) =>
      systemToolIds.includes(action.name)
    );
    const otherTools = allActions.filter(
      (action) => !systemToolIds.includes(action.name)
    );

    // Sort each group by display name
    systemTools.sort((a, b) => a.display_name.localeCompare(b.display_name));
    otherTools.sort((a, b) => a.display_name.localeCompare(b.display_name));

    // Return system tools first, then other tools
    return [...systemTools, ...otherTools];
  }, [agents]);

  const filteredActions = useMemo(() => {
    if (!actionsSearchQuery) return uniqueActions;
    return uniqueActions.filter((action) =>
      action.display_name
        .toLowerCase()
        .includes(actionsSearchQuery.toLowerCase())
    );
  }, [uniqueActions, actionsSearchQuery]);

  const memoizedCurrentlyVisibleAgents = useMemo(() => {
    return agents.filter((agent) => {
      const nameMatches = agent.name
        .toLowerCase()
        .includes(searchQuery.toLowerCase());
      const labelMatches = agent.labels?.some((label) =>
        label.name.toLowerCase().includes(searchQuery.toLowerCase())
      );

      const mineFilter =
        activeTab === "your" ? checkUserOwnsAgent(user, agent) : true;
      const isNotUnifiedAgent = agent.id !== 0;

      const creatorFilter =
        selectedCreatorIds.size === 0 ||
        (agent.owner && selectedCreatorIds.has(agent.owner.id));

      const actionsFilter =
        selectedActionIds.size === 0 ||
        agent.tools.some((tool) => selectedActionIds.has(tool.id));

      return (
        (nameMatches || labelMatches) &&
        mineFilter &&
        isNotUnifiedAgent &&
        creatorFilter &&
        actionsFilter
      );
    });
  }, [
    agents,
    searchQuery,
    activeTab,
    user,
    selectedCreatorIds,
    selectedActionIds,
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

  const creatorFilterButtonText = useMemo(() => {
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

  const actionsFilterButtonText = useMemo(() => {
    if (selectedActionIds.size === 0) {
      return "All Actions";
    } else if (selectedActionIds.size === 1) {
      const selectedId = Array.from(selectedActionIds)[0];
      const action = uniqueActions.find((a) => a.id === selectedId);
      return action?.display_name || "All Actions";
    } else {
      return `${selectedActionIds.size} selected`;
    }
  }, [selectedActionIds, uniqueActions]);

  return (
    <PageWrapper data-testid="AgentsPage/container" aria-label="Agents Page">
      <PageHeader
        icon={SvgOnyxOctagon}
        title="Agents & Assistants"
        description="Customize AI behavior and knowledge for you and your team’s use cases."
        className="bg-background-tint-01"
        rightChildren={
          <div data-testid="AgentsPage/new-agent-button">
            <Button href="/assistants/new" leftIcon={SvgPlus}>
              New Agent
            </Button>
          </div>
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
              onValueChange={(value) => setActiveTab(value as "all" | "your")}
            >
              <TabsList>
                <TabsTrigger value="all">All Agents</TabsTrigger>
                <TabsTrigger value="your">Your Agents</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <div className="flex flex-row gap-2">
            <Popover
              open={creatorFilterOpen}
              onOpenChange={setCreatorFilterOpen}
            >
              <PopoverTrigger asChild>
                <FilterButton
                  leftIcon={SvgUser}
                  active={selectedCreatorIds.size > 0}
                  transient={creatorFilterOpen}
                  onClear={() => setSelectedCreatorIds(new Set())}
                >
                  {creatorFilterButtonText}
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
                      value={creatorSearchQuery}
                      onChange={(e) => setCreatorSearchQuery(e.target.value)}
                    />,
                    ...filteredCreators.flatMap((creator, index) => {
                      const isSelected = selectedCreatorIds.has(creator.id);
                      const isCurrentUser = user && creator.id === user.id;

                      // Check if we need to add a separator after this item
                      const nextCreator = filteredCreators[index + 1];
                      const nextIsCurrentUser =
                        user && nextCreator && nextCreator.id === user.id;
                      const needsSeparator =
                        isCurrentUser && nextCreator && !nextIsCurrentUser;

                      // Determine icon: Check if selected, User icon if current user, otherwise no icon
                      const icon = isSelected
                        ? SvgCheck
                        : isCurrentUser
                          ? SvgUser
                          : () => null;

                      const lineItem = (
                        <LineItem
                          key={creator.id}
                          icon={icon}
                          heavyForced={isSelected}
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

                      // Return the line item, and optionally a separator
                      return needsSeparator ? [lineItem, null] : [lineItem];
                    }),
                  ]}
                </PopoverMenu>
              </PopoverContent>
            </Popover>
            <Popover
              open={actionsFilterOpen}
              onOpenChange={setActionsFilterOpen}
            >
              <PopoverTrigger asChild>
                <FilterButton
                  leftIcon={SvgActions}
                  transient={actionsFilterOpen}
                  active={selectedActionIds.size > 0}
                  onClear={() => setSelectedActionIds(new Set())}
                >
                  {actionsFilterButtonText}
                </FilterButton>
              </PopoverTrigger>
              <PopoverContent align="start">
                <PopoverMenu medium>
                  {[
                    <InputTypeIn
                      key="actions"
                      placeholder="Filter actions..."
                      internal
                      leftSearchIcon
                      value={actionsSearchQuery}
                      onChange={(e) => setActionsSearchQuery(e.target.value)}
                    />,
                    ...filteredActions.flatMap((action, index) => {
                      const isSelected = selectedActionIds.has(action.id);
                      const systemIcon = SYSTEM_TOOL_ICONS[action.name];
                      const isSystemTool = !!systemIcon;

                      // Check if we need to add a separator after this item
                      const nextAction = filteredActions[index + 1];
                      const nextIsSystemTool = nextAction
                        ? !!SYSTEM_TOOL_ICONS[nextAction.name]
                        : false;
                      const needsSeparator =
                        isSystemTool && nextAction && !nextIsSystemTool;

                      // Determine icon: Check if selected, system icon if available, otherwise Actions icon
                      const icon = isSelected
                        ? SvgCheck
                        : systemIcon
                          ? systemIcon
                          : SvgActions;

                      const lineItem = (
                        <LineItem
                          key={action.id}
                          icon={icon}
                          heavyForced={isSelected}
                          onClick={() => {
                            setSelectedActionIds((prev) => {
                              const newSet = new Set(prev);
                              if (newSet.has(action.id)) {
                                newSet.delete(action.id);
                              } else {
                                newSet.add(action.id);
                              }
                              return newSet;
                            });
                          }}
                        >
                          {action.display_name}
                        </LineItem>
                      );

                      // Return the line item, and optionally a separator
                      return needsSeparator ? [lineItem, null] : [lineItem];
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
