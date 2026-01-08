"use client";

import { useMemo, useState, useRef, useEffect } from "react";
import AgentCard from "@/refresh-components/AgentCard";
import { useUser } from "@/components/user/UserProvider";
import { checkUserOwnsAssistant as checkUserOwnsAgent } from "@/lib/assistants/checkOwnership";
import { useAgents } from "@/hooks/useAgents";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import CounterSeparator from "@/refresh-components/CounterSeparator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import FilterButton from "@/refresh-components/buttons/FilterButton";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import Button from "@/refresh-components/buttons/Button";
import {
  SEARCH_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
  OPEN_URL_TOOL_ID,
  OPEN_URL_TOOL_NAME,
  WEB_SEARCH_TOOL_ID,
  SYSTEM_TOOL_ICONS,
} from "@/app/chat/components/tools/constants";
import {
  SvgActions,
  SvgCheck,
  SvgOnyxOctagon,
  SvgPlus,
  SvgUser,
} from "@opal/icons";
import useOnMount from "@/hooks/useOnMount";

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
  const [selectedMcpServerIds, setSelectedMcpServerIds] = useState<Set<number>>(
    new Set()
  );
  const [creatorSearchQuery, setCreatorSearchQuery] = useState("");
  const [actionsSearchQuery, setActionsSearchQuery] = useState("");
  const [mcpServersMap, setMcpServersMap] = useState<
    Map<number, { id: number; name: string }>
  >(new Map());
  const searchInputRef = useRef<HTMLInputElement>(null);

  useOnMount(() => {
    // Focus the search input when the page loads
    searchInputRef.current?.focus();
  });

  // Fetch all MCP servers used by agents
  useEffect(() => {
    const fetchMCPServers = async () => {
      const serverIds = new Set<number>();
      agents.forEach((agent) => {
        agent.tools.forEach((tool) => {
          if (tool.mcp_server_id !== null && tool.mcp_server_id !== undefined) {
            serverIds.add(tool.mcp_server_id);
          }
        });
      });

      if (serverIds.size === 0) return;

      const serversMap = new Map<number, { id: number; name: string }>();

      // Fetch server data for each unique server ID
      for (const serverId of Array.from(serverIds)) {
        try {
          // We need to fetch from an agent that has this server
          const agentWithServer = agents.find((agent) =>
            agent.tools.some((tool) => tool.mcp_server_id === serverId)
          );

          if (agentWithServer) {
            const response = await fetch(
              `/api/mcp/servers/persona/${agentWithServer.id}`
            );
            if (response.ok) {
              const data = await response.json();
              const server = data.mcp_servers?.find(
                (s: any) => s.id === serverId
              );
              if (server) {
                serversMap.set(serverId, { id: server.id, name: server.name });
              }
            }
          }
        } catch (error) {
          console.error(`Error fetching MCP server ${serverId}:`, error);
        }
      }

      setMcpServersMap(serversMap);
    };

    fetchMCPServers();
  }, [agents]);

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
      {
        id: number;
        name: string;
        display_name: string;
        mcp_server_id?: number | null;
      }
    >();
    agents.forEach((agent) => {
      agent.tools.forEach((tool) => {
        if (
          tool.in_code_tool_id === OPEN_URL_TOOL_ID ||
          tool.name === OPEN_URL_TOOL_ID ||
          tool.name === OPEN_URL_TOOL_NAME
        ) {
          return;
        }
        actionsMap.set(tool.id, {
          id: tool.id,
          name: tool.name,
          display_name: tool.display_name,
          mcp_server_id: tool.mcp_server_id,
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

    // Group ALL tools by mcp_server_id (both system and other)
    const mcpGroupsMap = new Map<number, typeof allActions>();
    const nonMcpSystemTools: typeof systemTools = [];
    const nonMcpOtherTools: typeof otherTools = [];

    // Group system tools by MCP server
    systemTools.forEach((tool) => {
      if (tool.mcp_server_id !== null && tool.mcp_server_id !== undefined) {
        const group = mcpGroupsMap.get(tool.mcp_server_id) || [];
        group.push(tool);
        mcpGroupsMap.set(tool.mcp_server_id, group);
      } else {
        nonMcpSystemTools.push(tool);
      }
    });

    // Group other tools by MCP server
    otherTools.forEach((tool) => {
      if (tool.mcp_server_id !== null && tool.mcp_server_id !== undefined) {
        const group = mcpGroupsMap.get(tool.mcp_server_id) || [];
        group.push(tool);
        mcpGroupsMap.set(tool.mcp_server_id, group);
      } else {
        nonMcpOtherTools.push(tool);
      }
    });

    // Create grouped action items
    type ActionItem =
      | {
          type: "tool";
          id: number;
          name: string;
          display_name: string;
          mcp_server_id?: number | null;
        }
      | {
          type: "mcp_group";
          mcp_server_id: number;
          server_name: string;
          tools: Array<{ id: number; name: string; display_name: string }>;
        };

    const mcpGroupItems: ActionItem[] = Array.from(mcpGroupsMap.entries()).map(
      ([serverId, tools]) => {
        const serverInfo = mcpServersMap.get(serverId);
        return {
          type: "mcp_group" as const,
          mcp_server_id: serverId,
          server_name: serverInfo?.name || `MCP Server ${serverId}`,
          tools: tools.map((t) => ({
            id: t.id,
            name: t.name,
            display_name: t.display_name,
          })),
        };
      }
    );

    const nonMcpSystemToolItems: ActionItem[] = nonMcpSystemTools.map(
      (tool) => ({ type: "tool" as const, ...tool })
    );
    const nonMcpOtherToolItems: ActionItem[] = nonMcpOtherTools.map((tool) => ({
      type: "tool" as const,
      ...tool,
    }));

    // Return non-MCP system tools first, then MCP groups, then non-MCP other tools
    return [
      ...nonMcpSystemToolItems,
      ...mcpGroupItems,
      ...nonMcpOtherToolItems,
    ];
  }, [agents, mcpServersMap]);

  const filteredActions = useMemo(() => {
    if (!actionsSearchQuery) return uniqueActions;

    const query = actionsSearchQuery.toLowerCase();
    return uniqueActions.filter((action) => {
      if (action.type === "tool") {
        return action.display_name.toLowerCase().includes(query);
      } else {
        // For MCP groups, search through all tool names in the group
        return action.tools.some((tool) =>
          tool.display_name.toLowerCase().includes(query)
        );
      }
    });
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
        (selectedActionIds.size === 0 && selectedMcpServerIds.size === 0) ||
        agent.tools.some(
          (tool) =>
            selectedActionIds.has(tool.id) ||
            (tool.mcp_server_id !== null &&
              tool.mcp_server_id !== undefined &&
              selectedMcpServerIds.has(tool.mcp_server_id))
        );

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
    selectedMcpServerIds,
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
      return `By ${creator?.email}` || "Everyone";
    } else {
      return `${selectedCreatorIds.size} people`;
    }
  }, [selectedCreatorIds, uniqueCreators]);

  const actionsFilterButtonText = useMemo(() => {
    const totalSelected = selectedActionIds.size + selectedMcpServerIds.size;

    if (totalSelected === 0) {
      return "All Actions";
    } else if (totalSelected === 1) {
      // Check if it's a single tool
      if (selectedActionIds.size === 1) {
        const selectedId = Array.from(selectedActionIds)[0];
        for (const action of uniqueActions) {
          if (action.type === "tool" && action.id === selectedId) {
            return action.display_name;
          }
        }
      }

      // Check if it's a single MCP server
      if (selectedMcpServerIds.size === 1) {
        const selectedServerId = Array.from(selectedMcpServerIds)[0];
        for (const action of uniqueActions) {
          if (
            action.type === "mcp_group" &&
            action.mcp_server_id === selectedServerId
          ) {
            return action.server_name;
          }
        }
      }

      return "All Actions";
    } else {
      return `${totalSelected} selected`;
    }
  }, [selectedActionIds, selectedMcpServerIds, uniqueActions]);

  return (
    <SettingsLayouts.Root
      data-testid="AgentsPage/container"
      aria-label="Agents Page"
    >
      <SettingsLayouts.Header
        icon={SvgOnyxOctagon}
        title="Agents & Assistants"
        description="Customize AI behavior and knowledge for you and your team’s use cases."
        rightChildren={
          <div data-testid="AgentsPage/new-agent-button">
            <Button href="/chat/agents/create" leftIcon={SvgPlus}>
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
                      const icon = isCurrentUser
                        ? SvgUser
                        : isSelected
                          ? SvgCheck
                          : () => null;

                      const lineItem = (
                        <LineItem
                          key={creator.id}
                          icon={icon}
                          selected={isSelected}
                          emphasized
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
                  active={
                    selectedActionIds.size > 0 || selectedMcpServerIds.size > 0
                  }
                  onClear={() => {
                    setSelectedActionIds(new Set());
                    setSelectedMcpServerIds(new Set());
                  }}
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
                      if (action.type === "tool") {
                        const isSelected = selectedActionIds.has(action.id);
                        const systemIcon = SYSTEM_TOOL_ICONS[action.name];
                        const isSystemTool = !!systemIcon;

                        // Check if we need to add a separator after this item
                        const nextAction = filteredActions[index + 1];
                        const nextIsSystemTool =
                          nextAction && nextAction.type === "tool"
                            ? !!SYSTEM_TOOL_ICONS[nextAction.name]
                            : false;
                        const needsSeparator =
                          isSystemTool && nextAction && !nextIsSystemTool;

                        // Determine icon: system icon if available, otherwise Actions icon
                        const icon = systemIcon ? systemIcon : SvgActions;

                        const lineItem = (
                          <LineItem
                            key={action.id}
                            icon={icon}
                            selected={isSelected}
                            emphasized
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

                        return needsSeparator ? [lineItem, null] : [lineItem];
                      } else {
                        // MCP Group - render only the server name, not individual tools
                        const groupKey = `mcp-group-${action.mcp_server_id}`;
                        const isSelected = selectedMcpServerIds.has(
                          action.mcp_server_id
                        );

                        const lineItem = (
                          <LineItem
                            key={groupKey}
                            icon={SvgActions}
                            selected={isSelected}
                            emphasized
                            onClick={() => {
                              setSelectedMcpServerIds((prev) => {
                                const newSet = new Set(prev);
                                if (newSet.has(action.mcp_server_id)) {
                                  newSet.delete(action.mcp_server_id);
                                } else {
                                  newSet.add(action.mcp_server_id);
                                }
                                return newSet;
                              });
                            }}
                          >
                            {action.server_name}
                          </LineItem>
                        );

                        return [lineItem];
                      }
                    }),
                  ]}
                </PopoverMenu>
              </PopoverContent>
            </Popover>
          </div>
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
            <CounterSeparator
              count={agentCount}
              text={agentCount === 1 ? "Agent" : "Agents"}
            />
          </>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
