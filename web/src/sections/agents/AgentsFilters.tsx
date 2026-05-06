"use client";

/**
 * AgentsFilters — shared filter bar for agent lists.
 *
 * Renders "Created By" and "Actions" filter popovers that let users narrow
 * an agent list by creator and by attached tools/MCP servers.
 *
 * Usage:
 *
 * ```tsx
 * const { filtered, filterBar } = useAgentsFilters(agents);
 *
 * return (
 *   <>
 *     <div className="flex flex-row gap-2">{filterBar}</div>
 *     {filtered.map(agent => <AgentCard agent={agent} />)}
 *   </>
 * );
 * ```
 *
 * `useAgentsFilters` returns:
 * - `filtered` — the input agents array with creator and action filters
 *   applied. When no filters are active, this is the original array.
 * - `filterBar` — a React node containing the two filter popovers, ready to
 *   render inline.
 */

import { useMemo, useState } from "react";
import { FilterButton, LineItemButton } from "@opal/components";
import { SvgActions, SvgUser } from "@opal/icons";
import Popover, { PopoverMenu } from "@/refresh-components/Popover";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import useFilter from "@/hooks/useFilter";
import useMcpServers from "@/hooks/useMcpServers";
import { useAvailableTools } from "@/hooks/useAvailableTools";
import useUsers from "@/hooks/useUsers";
import { useUser } from "@/providers/UserProvider";
import type { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import {
  OPEN_URL_TOOL_ID,
  OPEN_URL_TOOL_NAME,
  SYSTEM_TOOL_ICONS,
} from "@/app/app/components/tools/constants";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Discriminated union for action filter items.
 * - `"tool"` — an individual tool (system or OpenAPI/custom).
 * - `"mcp_server"` — an MCP server, grouping all its tools into one entry.
 */
type ActionFilterItem =
  | { type: "mcp_server"; mcpServerId: number; name: string }
  | { type: "tool"; toolId: number; name: string; systemIcon?: React.FC };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Produces a unique string key for each action filter item. */
function actionFilterKey(item: ActionFilterItem): string {
  return item.type === "mcp_server"
    ? `mcp:${item.mcpServerId}`
    : `tool:${item.toolId}`;
}

/** Returns true when the item is a built-in system tool (Search, Web Search, etc.). */
function isSystemTool(item: ActionFilterItem): boolean {
  return item.type === "tool" && !!item.systemIcon;
}

// ---------------------------------------------------------------------------
// useAgentsFilters
// ---------------------------------------------------------------------------

interface UseAgentsFiltersReturn<T extends MinimalPersonaSnapshot> {
  /** The input agents with all active filters applied. */
  filtered: T[];

  /** A React node containing the two filter popovers, ready to render. */
  filterBar: React.ReactNode;
}

/**
 * Hook that drives the agent filter bar.
 *
 * Accepts an array of agents, derives the available creators and actions,
 * and returns the filtered agents plus a renderable `filterBar`.
 */
export function useAgentsFilters<T extends MinimalPersonaSnapshot>(
  agents: T[]
): UseAgentsFiltersReturn<T> {
  const { user } = useUser();
  const { mcpData } = useMcpServers();
  const { tools: allTools } = useAvailableTools();
  const { data: usersData } = useUsers({ includeApiKeys: false });

  // -- Selection state -------------------------------------------------------

  const [selectedCreatorIds, setSelectedCreatorIds] = useState<Set<string>>(
    new Set()
  );
  const [selectedActionKeys, setSelectedActionKeys] = useState<Set<string>>(
    new Set()
  );

  // -- MCP server name lookup ------------------------------------------------

  const mcpServerNames = useMemo(() => {
    const names = new Map<number, string>();
    for (const server of mcpData?.mcp_servers ?? []) {
      names.set(server.id, server.name);
    }
    return names;
  }, [mcpData]);

  // -- Creator filter data ---------------------------------------------------

  /** All users in the organization, with the current user first. */
  const uniqueCreators = useMemo(() => {
    let creators = (usersData?.accepted ?? [])
      .map((u) => ({ id: u.id, email: u.email }))
      .sort((a, b) => a.email.localeCompare(b.email));

    // Pin current user to top
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
  }, [usersData, user]);

  const creatorFilter = useFilter(uniqueCreators, (c) => c.email);

  // -- Actions filter data ---------------------------------------------------

  /**
   * Unique actions derived from ALL available tools (not just those on the
   * passed-in agents). This ensures the dropdown is consistent across all
   * pages.
   *
   * Ordering: system tools first (with their dedicated icons), then MCP
   * servers (grouped — one entry per server, not per tool), then
   * OpenAPI/custom actions.
   */
  const uniqueActions: ActionFilterItem[] = useMemo(() => {
    const seenMcpServers = new Set<number>();
    const individualTools = new Map<
      number,
      { id: number; name: string; systemIcon?: React.FC }
    >();

    allTools.forEach((tool) => {
      // Skip OpenURL — implicit tool, not user-facing
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
  }, [allTools, mcpServerNames]);

  const actionsFilter = useFilter(uniqueActions, (a) => a.name);

  // -- Derived selection sets ------------------------------------------------

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

  // -- Filter button labels --------------------------------------------------

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

  // -- Filtered agents -------------------------------------------------------

  const filtered = useMemo(() => {
    // No filters active — return the original array (preserves identity)
    if (selectedCreatorIds.size === 0 && selectedActionKeys.size === 0) {
      return agents;
    }

    return agents.filter((agent) => {
      const creatorMatch =
        selectedCreatorIds.size === 0 ||
        (agent.owner != null && selectedCreatorIds.has(agent.owner.id));

      const actionsMatch =
        selectedActionKeys.size === 0 ||
        agent.tools.some(
          (tool) =>
            selectedToolIds.has(tool.id) ||
            (tool.mcp_server_id != null &&
              selectedMcpServerIds.has(tool.mcp_server_id))
        );

      return creatorMatch && actionsMatch;
    });
  }, [
    agents,
    selectedCreatorIds,
    selectedActionKeys,
    selectedToolIds,
    selectedMcpServerIds,
  ]);

  // -- filterBar node --------------------------------------------------------

  const filterBar = (
    <>
      {/* Created By filter */}
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
                value={creatorFilter.query}
                onChange={(e) => creatorFilter.setQuery(e.target.value)}
              />,
              ...creatorFilter.filtered.map((creator) => {
                const isSelected = selectedCreatorIds.has(creator.id);
                const isCurrentUser = user != null && creator.id === user.id;

                return (
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
                  />
                );
              }),
            ]}
          </PopoverMenu>
        </Popover.Content>
      </Popover>

      {/* Actions filter */}
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
                value={actionsFilter.query}
                onChange={(e) => actionsFilter.setQuery(e.target.value)}
              />,
              ...actionsFilter.filtered.flatMap((action, index) => {
                const key = actionFilterKey(action);
                const isSelected = selectedActionKeys.has(key);
                const icon =
                  action.type === "tool" && action.systemIcon
                    ? action.systemIcon
                    : SvgActions;

                // Separator between system tools and the rest
                const nextAction = actionsFilter.filtered[index + 1];
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
    </>
  );

  return { filtered, filterBar };
}
