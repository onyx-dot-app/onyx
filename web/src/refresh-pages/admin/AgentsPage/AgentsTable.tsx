"use client";

import { useEffect, useMemo, useState } from "react";
import { Table, createTableColumns, FilterButton } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import type { MinimalUserSnapshot } from "@/lib/types";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import type { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { useAdminPersonas } from "@/hooks/useAdminPersonas";
import { toast } from "@/hooks/useToast";
import AgentRowActions from "@/refresh-pages/admin/AgentsPage/AgentRowActions";
import { updateAgentDisplayPriorities } from "@/refresh-pages/admin/AgentsPage/svc";
import type { AgentRow } from "@/refresh-pages/admin/AgentsPage/interfaces";
import type { Persona } from "@/app/admin/agents/interfaces";
import { SvgActions, SvgCheck, SvgUser } from "@opal/icons";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import { useUser } from "@/providers/UserProvider";
import {
  OPEN_URL_TOOL_ID,
  OPEN_URL_TOOL_NAME,
  SYSTEM_TOOL_ICONS,
} from "@/app/app/components/tools/constants";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ActionFilterItem =
  | { type: "mcp_server"; mcpServerId: number; name: string }
  | { type: "tool"; toolId: number; name: string; systemIcon?: React.FC };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toAgentRow(persona: Persona): AgentRow {
  return {
    id: persona.id,
    name: persona.name,
    description: persona.description,
    is_public: persona.is_public,
    is_listed: persona.is_listed,
    is_featured: persona.is_featured,
    builtin_persona: persona.builtin_persona,
    display_priority: persona.display_priority,
    owner: persona.owner,
    groups: persona.groups,
    users: persona.users,
    tools: persona.tools,
    uploaded_image_id: persona.uploaded_image_id,
    icon_name: persona.icon_name,
  };
}

function actionFilterKey(item: ActionFilterItem): string {
  return item.type === "mcp_server"
    ? `mcp:${item.mcpServerId}`
    : `tool:${item.toolId}`;
}

function isSystemTool(item: ActionFilterItem): boolean {
  return item.type === "tool" && !!item.systemIcon;
}

// ---------------------------------------------------------------------------
// Column renderers
// ---------------------------------------------------------------------------

function renderCreatedByColumn(
  _value: MinimalUserSnapshot | null,
  row: AgentRow
) {
  return (
    <Content
      sizePreset="main-ui"
      variant="section"
      icon={SvgUser}
      title={row.builtin_persona ? "System" : row.owner?.email ?? "\u2014"}
    />
  );
}

function getAccessTitle(row: AgentRow): string {
  if (row.is_public) return "Public";
  if (row.groups.length > 0 || row.users.length > 0) return "Shared";
  return "Private";
}

function renderAccessColumn(_isPublic: boolean, row: AgentRow) {
  return (
    <Content
      sizePreset="main-ui"
      variant="section"
      title={getAccessTitle(row)}
      description={
        !row.is_listed ? "Unlisted" : row.is_featured ? "Featured" : undefined
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<AgentRow>();

function buildColumns(onMutate: () => void) {
  return [
    tc.qualifier({
      content: "icon",
      background: true,
      getContent: (row) => (props) => (
        <AgentAvatar
          agent={row as unknown as MinimalPersonaSnapshot}
          size={props.size}
        />
      ),
    }),
    tc.column("name", {
      header: "Name",
      weight: 25,
      cell: (value) => (
        <Text as="span" mainUiBody text05>
          {value}
        </Text>
      ),
    }),
    tc.column("description", {
      header: "Description",
      weight: 35,
      cell: (value) => (
        <Text as="span" mainUiBody text03>
          {value || "\u2014"}
        </Text>
      ),
    }),
    tc.column("owner", {
      header: "Created By",
      weight: 20,
      cell: renderCreatedByColumn,
    }),
    tc.column("is_public", {
      header: "Access",
      weight: 12,
      cell: renderAccessColumn,
    }),
    tc.actions({
      cell: (row) => <AgentRowActions agent={row} onMutate={onMutate} />,
    }),
  ];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 10;

export default function AgentsTable() {
  const [searchTerm, setSearchTerm] = useState("");
  const { user } = useUser();

  // Filter state
  const [creatorFilterOpen, setCreatorFilterOpen] = useState(false);
  const [actionsFilterOpen, setActionsFilterOpen] = useState(false);
  const [selectedCreatorIds, setSelectedCreatorIds] = useState<Set<string>>(
    new Set()
  );
  const [selectedActionKeys, setSelectedActionKeys] = useState<Set<string>>(
    new Set()
  );
  const [creatorSearchQuery, setCreatorSearchQuery] = useState("");
  const [actionsSearchQuery, setActionsSearchQuery] = useState("");

  // MCP server names — fetched once for the filter dropdown
  const [mcpServerNames, setMcpServerNames] = useState<Map<number, string>>(
    new Map()
  );

  const { personas, isLoading, error, refresh } = useAdminPersonas();

  const columns = useMemo(() => buildColumns(refresh), [refresh]);

  const allAgentRows: AgentRow[] = useMemo(
    () => personas.filter((p) => !p.builtin_persona).map(toAgentRow),
    [personas]
  );

  // Collect all MCP server IDs referenced by agents, then fetch names
  const mcpServerIds = useMemo(() => {
    const ids = new Set<number>();
    allAgentRows.forEach((agent) => {
      agent.tools.forEach((tool) => {
        if (tool.mcp_server_id != null) ids.add(tool.mcp_server_id);
      });
    });
    return ids;
  }, [allAgentRows]);

  useEffect(() => {
    if (mcpServerIds.size === 0) return;

    (async () => {
      try {
        const res = await fetch("/api/admin/mcp/servers");
        if (!res.ok) return;
        const data = await res.json();
        const names = new Map<number, string>();
        for (const server of data.mcp_servers ?? []) {
          if (mcpServerIds.has(server.id)) {
            names.set(server.id, server.name);
          }
        }
        setMcpServerNames(names);
      } catch {
        // Silently fall back to "MCP Server {id}" labels
      }
    })();
  }, [mcpServerIds]);

  // ---------------------------------------------------------------------------
  // Creator filter data
  // ---------------------------------------------------------------------------

  const uniqueCreators = useMemo(() => {
    const creatorsMap = new Map<string, { id: string; email: string }>();
    allAgentRows.forEach((agent) => {
      if (agent.owner) {
        creatorsMap.set(agent.owner.id, agent.owner);
      }
    });

    let creators = Array.from(creatorsMap.values()).sort((a, b) =>
      a.email.localeCompare(b.email)
    );

    if (user) {
      const hasCurrentUser = creators.some((c) => c.id === user.id);
      if (!hasCurrentUser) {
        creators = [{ id: user.id, email: user.email }, ...creators];
      } else {
        creators = creators.sort((a, b) => {
          if (a.id === user.id) return -1;
          if (b.id === user.id) return 1;
          return a.email.localeCompare(b.email);
        });
      }
    }

    return creators;
  }, [allAgentRows, user]);

  const filteredCreators = useMemo(() => {
    if (!creatorSearchQuery) return uniqueCreators;
    return uniqueCreators.filter((creator) =>
      creator.email.toLowerCase().includes(creatorSearchQuery.toLowerCase())
    );
  }, [uniqueCreators, creatorSearchQuery]);

  // ---------------------------------------------------------------------------
  // Actions filter data
  // ---------------------------------------------------------------------------

  const uniqueActions: ActionFilterItem[] = useMemo(() => {
    const seenMcpServers = new Set<number>();
    const individualTools = new Map<
      number,
      { id: number; name: string; systemIcon?: React.FC }
    >();

    allAgentRows.forEach((agent) => {
      agent.tools.forEach((tool) => {
        // Skip OpenURL — it's an implicit tool, not a user-facing action
        if (
          tool.in_code_tool_id === OPEN_URL_TOOL_ID ||
          tool.name === OPEN_URL_TOOL_ID ||
          tool.name === OPEN_URL_TOOL_NAME
        ) {
          return;
        }

        if (tool.mcp_server_id != null) {
          seenMcpServers.add(tool.mcp_server_id);
        } else {
          individualTools.set(tool.id, {
            id: tool.id,
            name: tool.display_name,
            systemIcon: SYSTEM_TOOL_ICONS[tool.name],
          });
        }
      });
    });

    // System tools first, then MCP servers, then OpenAPI/custom actions
    const toolItems = Array.from(individualTools.values());
    const systemItems: ActionFilterItem[] = toolItems
      .filter((t) => !!t.systemIcon)
      .map((t) => ({ type: "tool" as const, toolId: t.id, ...t }))
      .sort((a, b) => a.name.localeCompare(b.name));

    const mcpItems: ActionFilterItem[] = Array.from(seenMcpServers)
      .map((id) => ({
        type: "mcp_server" as const,
        mcpServerId: id,
        name: mcpServerNames.get(id) ?? `MCP Server ${id}`,
      }))
      .sort((a, b) => a.name.localeCompare(b.name));

    const otherItems: ActionFilterItem[] = toolItems
      .filter((t) => !t.systemIcon)
      .map((t) => ({ type: "tool" as const, toolId: t.id, ...t }))
      .sort((a, b) => a.name.localeCompare(b.name));

    return [...systemItems, ...mcpItems, ...otherItems];
  }, [allAgentRows, mcpServerNames]);

  const filteredActions = useMemo(() => {
    if (!actionsSearchQuery) return uniqueActions;
    const query = actionsSearchQuery.toLowerCase();
    return uniqueActions.filter((a) => a.name.toLowerCase().includes(query));
  }, [uniqueActions, actionsSearchQuery]);

  // ---------------------------------------------------------------------------
  // Filter button labels
  // ---------------------------------------------------------------------------

  const creatorFilterButtonText = useMemo(() => {
    if (selectedCreatorIds.size === 0) return "Everyone";
    if (selectedCreatorIds.size === 1) {
      const selectedId = Array.from(selectedCreatorIds)[0];
      const creator = uniqueCreators.find((c) => c.id === selectedId);
      return creator ? `By ${creator.email}` : "Everyone";
    }
    return `${selectedCreatorIds.size} people`;
  }, [selectedCreatorIds, uniqueCreators]);

  const actionsFilterButtonText = useMemo(() => {
    if (selectedActionKeys.size === 0) return "All Actions";
    if (selectedActionKeys.size === 1) {
      const key = Array.from(selectedActionKeys)[0];
      const item = uniqueActions.find((a) => actionFilterKey(a) === key);
      return item?.name ?? "All Actions";
    }
    return `${selectedActionKeys.size} selected`;
  }, [selectedActionKeys, uniqueActions]);

  // Derive selected MCP server IDs and individual tool IDs from keys
  const { selectedMcpServerIds, selectedToolIds } = useMemo(() => {
    const mcpIds = new Set<number>();
    const toolIds = new Set<number>();
    for (const key of Array.from(selectedActionKeys)) {
      if (key.startsWith("mcp:")) {
        mcpIds.add(Number(key.slice(4)));
      } else if (key.startsWith("tool:")) {
        toolIds.add(Number(key.slice(5)));
      }
    }
    return { selectedMcpServerIds: mcpIds, selectedToolIds: toolIds };
  }, [selectedActionKeys]);

  // ---------------------------------------------------------------------------
  // Filtered rows
  // ---------------------------------------------------------------------------

  const agentRows = useMemo(() => {
    return allAgentRows.filter((agent) => {
      const creatorFilter =
        selectedCreatorIds.size === 0 ||
        (agent.owner && selectedCreatorIds.has(agent.owner.id));

      const actionsFilter =
        selectedActionKeys.size === 0 ||
        agent.tools.some(
          (tool) =>
            selectedToolIds.has(tool.id) ||
            (tool.mcp_server_id != null &&
              selectedMcpServerIds.has(tool.mcp_server_id))
        );

      return creatorFilter && actionsFilter;
    });
  }, [
    allAgentRows,
    selectedCreatorIds,
    selectedActionKeys,
    selectedMcpServerIds,
    selectedToolIds,
  ]);

  // ---------------------------------------------------------------------------
  // Reorder handler
  // ---------------------------------------------------------------------------

  const handleReorder = async (
    _orderedIds: string[],
    changedOrders: Record<string, number>
  ) => {
    try {
      await updateAgentDisplayPriorities(changedOrders);
      refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update agent order"
      );
      refresh();
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <SimpleLoader className="h-6 w-6" />
      </div>
    );
  }

  if (error) {
    console.error("Failed to load agents:", error);
    return (
      <Text as="p" secondaryBody text03>
        Failed to load agents. Please try refreshing the page.
      </Text>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <InputTypeIn
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        placeholder="Search agents..."
        leftSearchIcon
      />
      <div className="flex flex-row gap-2">
        <Popover open={creatorFilterOpen} onOpenChange={setCreatorFilterOpen}>
          <Popover.Trigger asChild>
            <FilterButton
              icon={SvgUser}
              active={selectedCreatorIds.size > 0}
              onClear={() => setSelectedCreatorIds(new Set())}
            >
              {creatorFilterButtonText}
            </FilterButton>
          </Popover.Trigger>
          <Popover.Content align="start">
            <PopoverMenu>
              {[
                <InputTypeIn
                  key="created-by"
                  placeholder="Created by..."
                  variant="internal"
                  leftSearchIcon
                  value={creatorSearchQuery}
                  onChange={(e) => setCreatorSearchQuery(e.target.value)}
                />,
                ...filteredCreators.flatMap((creator) => {
                  const isSelected = selectedCreatorIds.has(creator.id);
                  const isCurrentUser = user && creator.id === user.id;

                  return [
                    <LineItem
                      key={creator.id}
                      icon={
                        isCurrentUser
                          ? SvgUser
                          : isSelected
                            ? SvgCheck
                            : () => null
                      }
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
                    </LineItem>,
                  ];
                }),
              ]}
            </PopoverMenu>
          </Popover.Content>
        </Popover>

        <Popover open={actionsFilterOpen} onOpenChange={setActionsFilterOpen}>
          <Popover.Trigger asChild>
            <FilterButton
              icon={SvgActions}
              active={selectedActionKeys.size > 0}
              onClear={() => setSelectedActionKeys(new Set())}
            >
              {actionsFilterButtonText}
            </FilterButton>
          </Popover.Trigger>
          <Popover.Content align="start">
            <PopoverMenu>
              {[
                <InputTypeIn
                  key="actions"
                  placeholder="Filter actions..."
                  variant="internal"
                  leftSearchIcon
                  value={actionsSearchQuery}
                  onChange={(e) => setActionsSearchQuery(e.target.value)}
                />,
                ...filteredActions.flatMap((action, index) => {
                  const key = actionFilterKey(action);
                  const isSelected = selectedActionKeys.has(key);
                  const icon =
                    action.type === "tool" && action.systemIcon
                      ? action.systemIcon
                      : SvgActions;

                  // Add separator after the last system tool
                  const nextAction = filteredActions[index + 1];
                  const needsSeparator =
                    isSystemTool(action) &&
                    nextAction &&
                    !isSystemTool(nextAction);

                  const lineItem = (
                    <LineItem
                      key={key}
                      icon={icon}
                      selected={isSelected}
                      emphasized
                      onClick={() => {
                        setSelectedActionKeys((prev) => {
                          const newSet = new Set(prev);
                          if (newSet.has(key)) {
                            newSet.delete(key);
                          } else {
                            newSet.add(key);
                          }
                          return newSet;
                        });
                      }}
                    >
                      {action.name}
                    </LineItem>
                  );

                  return needsSeparator ? [lineItem, null] : [lineItem];
                }),
              ]}
            </PopoverMenu>
          </Popover.Content>
        </Popover>
      </div>
      <Table
        data={agentRows}
        columns={columns}
        getRowId={(row) => String(row.id)}
        pageSize={PAGE_SIZE}
        searchTerm={searchTerm}
        draggable={{
          onReorder: handleReorder,
        }}
        emptyState={
          <IllustrationContent
            illustration={SvgNoResult}
            title="No agents found"
            description="No agents match the current search."
          />
        }
        footer={{}}
      />
    </div>
  );
}
