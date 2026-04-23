"use client";

/**
 * AgentFilters — shared filter bar for agent lists.
 *
 * Renders "Created By" and "Actions" filter popovers that let users narrow
 * an agent list by creator and by attached tools/MCP servers.
 *
 * Usage:
 *
 * ```tsx
 * const { matchesFilters, filterBar } = useAgentFilters(agents);
 *
 * const visible = agents.filter(matchesFilters);
 *
 * return (
 *   <>
 *     <div className="flex flex-row gap-2">{filterBar}</div>
 *     {visible.map(agent => <AgentCard agent={agent} />)}
 *   </>
 * );
 * ```
 *
 * `useAgentFilters` returns:
 * - `matchesFilters(agent)` — a stable predicate that returns `true` when the
 *   agent matches all currently active filters. Memoized so it's safe to use
 *   in dependency arrays.
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
import { useUser } from "@/providers/UserProvider";
import type { ToolSnapshot } from "@/lib/tools/interfaces";
import {
  OPEN_URL_TOOL_ID,
  OPEN_URL_TOOL_NAME,
  SYSTEM_TOOL_ICONS,
} from "@/app/app/components/tools/constants";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Minimal shape required from each agent for the filters to work. */
interface AgentLike {
  owner: { id: string; email: string } | null;
  tools: ToolSnapshot[];
}

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
// useAgentFilters
// ---------------------------------------------------------------------------

interface UseAgentFiltersReturn {
  /**
   * A stable filter predicate. Returns `true` when the agent matches all
   * currently active creator and action filters.
   *
   * Safe to include in `useMemo` / `useCallback` dependency arrays — it only
   * changes when the user toggles a filter.
   */
  matchesFilters: (agent: AgentLike) => boolean;

  /** A React node containing the two filter popovers, ready to render. */
  filterBar: React.ReactNode;
}

/**
 * Hook that drives the agent filter bar.
 *
 * Accepts any array of agent-like objects (must have `owner` and `tools`),
 * derives the available creators and actions, and returns a `matchesFilters`
 * predicate plus a renderable `filterBar`.
 */
export function useAgentFilters(agents: AgentLike[]): UseAgentFiltersReturn {
  const { user } = useUser();
  const { mcpData } = useMcpServers();

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

  /** Unique creators derived from the agent list, with the current user first. */
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
  }, [agents, user]);

  const creatorFilter = useFilter(uniqueCreators, (c) => c.email);

  // -- Actions filter data ---------------------------------------------------

  /**
   * Unique actions derived from the agent list.
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

    agents.forEach((agent) => {
      agent.tools.forEach((tool) => {
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
  }, [agents, mcpServerNames]);

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

  // -- matchesFilters predicate ----------------------------------------------

  const matchesFilters = useMemo(() => {
    return (agent: AgentLike): boolean => {
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
    };
  }, [
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

  return { matchesFilters, filterBar };
}
