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
import { useTranslations } from "next-intl";
import {
  Dropdown,
  FilterButton,
  type DropdownItem,
  type DropdownOption,
} from "@opal/components";
import { SvgActions, SvgUser } from "@opal/icons";
import { useAdminMcpServers } from "@/lib/mcp/hooks";
import { useAvailableTools } from "@/lib/tools/hooks";
import useUsers from "@/hooks/useUsers";
import { useUser } from "@/providers/UserProvider";
import type { MinimalAgent } from "@/lib/agents/types";
import {
  OPEN_URL_TOOL_ID,
  OPEN_URL_TOOL_NAME,
  SYSTEM_TOOL_ICONS,
} from "@/lib/tools/constants";

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

interface UseAgentsFiltersReturn<T extends MinimalAgent> {
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
export function useAgentsFilters<T extends MinimalAgent>(
  agents: T[]
): UseAgentsFiltersReturn<T> {
  const t = useTranslations("agents");
  const { user } = useUser();
  const { mcpData } = useAdminMcpServers();
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
    if (selectedCreatorIds.size === 0) return t("filters.creator.all.label");
    if (selectedCreatorIds.size === 1) {
      const selectedId = Array.from(selectedCreatorIds)[0];
      const creator = uniqueCreators.find((c) => c.id === selectedId);
      return creator
        ? t("filters.creator.single.label", { email: creator.email })
        : t("filters.creator.all.label");
    }
    return t("filters.creator.multiple.label", {
      count: selectedCreatorIds.size,
    });
  }, [selectedCreatorIds, uniqueCreators, t]);

  const actionsFilterButtonText = useMemo(() => {
    if (selectedActionKeys.size === 0) return t("filters.actions.all.label");
    if (selectedActionKeys.size === 1) {
      const key = Array.from(selectedActionKeys)[0];
      const item = uniqueActions.find((a) => actionFilterKey(a) === key);
      return item?.name ?? t("filters.actions.all.label");
    }
    return t("filters.actions.multiple.label", {
      count: selectedActionKeys.size,
    });
  }, [selectedActionKeys, uniqueActions, t]);

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

  const toggleIn =
    (setSelected: React.Dispatch<React.SetStateAction<Set<string>>>) =>
    (key: string) =>
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      });
  const toggleCreator = toggleIn(setSelectedCreatorIds);
  const toggleAction = toggleIn(setSelectedActionKeys);

  // Rows for the pickers. The list's own search filters them; system tools
  // sit in a group of their own, above the rest.
  const creatorItems: DropdownItem[] = uniqueCreators.map((creator) => ({
    kind: "option",
    value: creator.id,
    icon: SvgUser,
    title: creator.email,
    description:
      user != null && creator.id === user.id
        ? t("filters.creator.me.description")
        : undefined,
  }));
  const actionOption = (action: ActionFilterItem): DropdownOption => ({
    kind: "option",
    value: actionFilterKey(action),
    icon:
      action.type === "tool" && action.systemIcon
        ? action.systemIcon
        : SvgActions,
    title: action.name,
  });
  const systemActions = uniqueActions.filter(isSystemTool);
  const otherActions = uniqueActions.filter((a) => !isSystemTool(a));
  const actionItems: DropdownItem[] = [];
  if (systemActions.length > 0 && otherActions.length > 0) {
    actionItems.push(
      { kind: "group", items: systemActions.map(actionOption) },
      { kind: "group", items: otherActions.map(actionOption) }
    );
  } else {
    actionItems.push(...uniqueActions.map(actionOption));
  }

  const filterBar = (
    <>
      {/* Created By filter */}
      <Dropdown>
        <Dropdown.Trigger asChild>
          <FilterButton
            icon={SvgUser}
            active={selectedCreatorIds.size > 0}
            onClear={() => setSelectedCreatorIds(new Set())}
          >
            {creatorFilterButtonText}
          </FilterButton>
        </Dropdown.Trigger>
        <Dropdown.Data
          label={creatorFilterButtonText}
          search={{ placeholder: t("filters.creator.search.placeholder") }}
          values={selectedCreatorIds}
          onSelect={(option) => toggleCreator(option.value)}
          items={creatorItems}
        />
      </Dropdown>

      {/* Actions filter */}
      <Dropdown>
        <Dropdown.Trigger asChild>
          <FilterButton
            icon={SvgActions}
            active={selectedActionKeys.size > 0}
            onClear={() => setSelectedActionKeys(new Set())}
          >
            {actionsFilterButtonText}
          </FilterButton>
        </Dropdown.Trigger>
        <Dropdown.Data
          label={actionsFilterButtonText}
          search={{ placeholder: t("filters.actions.search.placeholder") }}
          values={selectedActionKeys}
          onSelect={(option) => toggleAction(option.value)}
          items={actionItems}
        />
      </Dropdown>
    </>
  );

  return { filtered, filterBar };
}
