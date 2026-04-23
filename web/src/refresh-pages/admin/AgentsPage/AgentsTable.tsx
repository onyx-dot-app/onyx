"use client";

import { useMemo, useState } from "react";
import { Table, createTableColumns, FilterButton } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import type { MinimalUserSnapshot } from "@/lib/types";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import type { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { useAdminAgents } from "@/hooks/useAgents";
import { toast } from "@/hooks/useToast";
import AgentRowActions from "@/refresh-pages/admin/AgentsPage/AgentRowActions";
import { updateAgentDisplayPriorities } from "@/refresh-pages/admin/AgentsPage/svc";
import type { AgentRow } from "@/refresh-pages/admin/AgentsPage/interfaces";
import type { Persona } from "@/app/admin/agents/interfaces";
import { SvgActions, SvgUser } from "@opal/icons";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import { LineItemButton } from "@opal/components";
import { useUser } from "@/providers/UserProvider";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";
import useFilter from "@/hooks/useFilter";
import useMcpServers from "@/hooks/useMcpServers";
import {
  OPEN_URL_TOOL_ID,
  OPEN_URL_TOOL_NAME,
  SYSTEM_TOOL_ICONS,
} from "@/app/app/components/tools/constants";
import { Section } from "@/layouts/general-layouts";

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

export default function AgentsTable() {
  const [searchTerm, setSearchTerm] = useState("");
  const { user } = useUser();

  // Filter state
  const [selectedCreatorIds, setSelectedCreatorIds] = useState<Set<string>>(
    new Set()
  );
  const [selectedActionKeys, setSelectedActionKeys] = useState<Set<string>>(
    new Set()
  );

  const { personas, isLoading, refresh } = useAdminAgents();
  const { mcpData } = useMcpServers();

  const columns = useMemo(() => buildColumns(refresh), [refresh]);

  const allAgentRows: AgentRow[] = useMemo(
    () => personas.filter((p) => !p.builtin_persona).map(toAgentRow),
    [personas]
  );

  const mcpServerNames = useMemo(() => {
    const names = new Map<number, string>();
    for (const server of mcpData?.mcp_servers ?? []) {
      names.set(server.id, server.name);
    }
    return names;
  }, [mcpData]);

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

  const {
    query: creatorSearchQuery,
    setQuery: setCreatorSearchQuery,
    filtered: filteredCreators,
  } = useFilter(uniqueCreators, (c) => c.email);

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

  const {
    query: actionsSearchQuery,
    setQuery: setActionsSearchQuery,
    filtered: filteredActions,
  } = useFilter(uniqueActions, (a) => a.name);

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

  async function handleReorder(
    _orderedIds: string[],
    changedOrders: Record<string, number>
  ) {
    try {
      await updateAgentDisplayPriorities(changedOrders);
      refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update agent order"
      );
      refresh();
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <SimpleLoader className="h-6 w-6" />
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <Section gap={0.5}>
        <InputTypeIn
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Search agents..."
          leftSearchIcon
        />
        <Section gap={0.25} flexDirection="row" justifyContent="start">
          <Popover>
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
                      <LineItemButton
                        key={creator.id}
                        sizePreset="main-ui"
                        rounding="sm"
                        selectVariant="select-heavy"
                        icon={SvgUser}
                        title={creator.email}
                        description={isCurrentUser ? "Me" : undefined}
                        state={isSelected ? "selected" : "empty"}
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
                      />,
                    ];
                  }),
                ]}
              </PopoverMenu>
            </Popover.Content>
          </Popover>

          <Popover>
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
                      <LineItemButton
                        key={key}
                        sizePreset="main-ui"
                        rounding="sm"
                        selectVariant="select-heavy"
                        icon={icon}
                        title={action.name}
                        state={isSelected ? "selected" : "empty"}
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
                      />
                    );

                    return needsSeparator ? [lineItem, null] : [lineItem];
                  }),
                ]}
              </PopoverMenu>
            </Popover.Content>
          </Popover>
        </Section>
      </Section>
      <Table
        data={agentRows}
        columns={columns}
        getRowId={(row) => String(row.id)}
        pageSize={DEFAULT_PAGE_SIZE}
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
