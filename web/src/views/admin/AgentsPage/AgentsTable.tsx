"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { OverflowText, Table, type TableColumn } from "@opal/components";
import { Content, IllustrationContent, toast } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { PageLoader } from "@opal/loaders";
import { InputTypeIn } from "@opal/components";
import type { MinimalUserSnapshot } from "@/lib/types";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import type { Agent } from "@/lib/agents/types";
import { useAdminAgents } from "@/lib/agents/hooks";
import AgentRowActions from "@/views/admin/AgentsPage/AgentRowActions";
import { updateAgentDisplayPriorities } from "@/lib/agents/svc";
import { SvgUser } from "@opal/icons";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";
import { Section } from "@/layouts/general-layouts";
import { useAgentsFilters } from "@/sections/agents/AgentsFilters";
import { can } from "@/lib/permissions/resource-actions";

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

/** Typographic placeholder for a blank cell. */
const BLANK_CELL = "—";

/** Matches the server's order: display_priority (nulls last), then |id|. */
function compareAgentOrder(a: Agent, b: Agent): number {
  const pa = a.display_priority ?? Number.POSITIVE_INFINITY;
  const pb = b.display_priority ?? Number.POSITIVE_INFINITY;
  if (pa !== pb) return pa - pb;
  return Math.abs(a.id) - Math.abs(b.id);
}

/**
 * Merges the reordered visible IDs back into the full agent order and returns
 * the priority map for every agent whose position changed. The table may show
 * a filtered subset, and untouched agents may have stale or null priorities,
 * so the whole list is renumbered.
 */
function buildDisplayPriorityMap(
  allAgents: Agent[],
  reorderedVisibleIds: string[]
) {
  const visible = new Set(reorderedVisibleIds);
  const queue = [...reorderedVisibleIds];
  const fullOrder = allAgents.map((agent) => {
    const id = String(agent.id);
    return visible.has(id) ? (queue.shift() ?? id) : id;
  });

  const priorityById = new Map(
    allAgents.map((agent) => [String(agent.id), agent.display_priority])
  );
  const changed: Record<string, number> = {};
  fullOrder.forEach((id, index) => {
    if (priorityById.get(id) !== index) changed[id] = index;
  });
  return changed;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AgentsTable() {
  const t = useTranslations("admin.agents");
  const [searchTerm, setSearchTerm] = useState("");

  const { agents, isLoading, refresh } = useAdminAgents();

  const columns = useMemo((): TableColumn<Agent>[] => {
    function renderCreatedByColumn(
      _value: MinimalUserSnapshot | null,
      row: Agent
    ) {
      return (
        <Content
          sizePreset="main-ui"
          variant="section"
          icon={SvgUser}
          titleMaxLines={1}
          title={
            row.builtin_persona
              ? t("table.createdBy.system.label")
              : (row.owner?.email ?? BLANK_CELL)
          }
        />
      );
    }

    function getAccessTitle(row: Agent): string {
      if (row.is_public) return t("table.access.public.label");
      // Group ownership counts as shared even with an empty share list
      if (row.groups.length > 0 || row.users.length > 0 || row.owner_group) {
        return t("table.access.shared.label");
      }
      return t("table.access.private.label");
    }

    function renderAccessColumn(_isPublic: boolean, row: Agent) {
      return (
        <Content
          sizePreset="main-ui"
          variant="section"
          title={getAccessTitle(row)}
          titleMaxLines={1}
          descriptionMaxLines={1}
          description={
            !row.is_listed
              ? t("table.access.unlisted.label")
              : row.is_featured
                ? t("table.access.featured.label")
                : undefined
          }
        />
      );
    }

    return [
      {
        kind: "qualifier",
        content: "icon",
        background: true,
        icon: (row) => (props) => <AgentAvatar agent={row} size={props.size} />,
      },
      {
        kind: "data",
        truncate: true,
        field: "name",
        title: t("table.nameColumn.header"),
        weight: 25,
        cell: (value) => (
          <OverflowText font="main-ui-body" color="text-05">
            {value}
          </OverflowText>
        ),
      },
      {
        kind: "data",
        truncate: true,
        field: "description",
        title: t("table.descriptionColumn.header"),
        weight: 35,
        cell: (value) => (
          <OverflowText font="main-ui-body" color="text-03">
            {value || BLANK_CELL}
          </OverflowText>
        ),
      },
      {
        kind: "data",
        truncate: true,
        field: "owner",
        title: t("table.createdByColumn.header"),
        weight: 20,
        cell: renderCreatedByColumn,
      },
      {
        kind: "data",
        truncate: true,
        field: "is_public",
        title: t("table.accessColumn.header"),
        weight: 12,
        cell: renderAccessColumn,
      },
      {
        kind: "actions",
        cell: (row) => <AgentRowActions agent={row} onMutate={refresh} />,
      },
    ];
  }, [refresh, t]);

  const nonBuiltinAgents = useMemo(
    () => agents.filter((p) => !p.builtin_persona).sort(compareAgentOrder),
    [agents]
  );

  const { filtered: filteredAgents, filterBar } =
    useAgentsFilters(nonBuiltinAgents);

  const canReorder = nonBuiltinAgents.some((agent) => can(agent, "reorder"));

  async function handleReorder(orderedIds: string[]) {
    const priorityMap = buildDisplayPriorityMap(nonBuiltinAgents, orderedIds);
    if (Object.keys(priorityMap).length === 0) return;

    // Apply the new order locally so the row does not snap back while saving.
    void refresh(
      (current) =>
        Array.isArray(current)
          ? current.map((agent) => {
              const priority = priorityMap[String(agent.id)];
              return priority === undefined
                ? agent
                : { ...agent, display_priority: priority };
            })
          : current,
      { revalidate: false }
    );

    try {
      await updateAgentDisplayPriorities(priorityMap);
      refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("reorderError.message")
      );
      refresh();
    }
  }

  if (isLoading) {
    return <PageLoader />;
  }

  return (
    <div className="flex flex-col">
      <Section gap={2}>
        <InputTypeIn
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder={t("search.placeholder")}
          searchIcon
        />
        <Section gap={1} flexDirection="row" justifyContent="start">
          {filterBar}
        </Section>
      </Section>
      <Table
        items={filteredAgents}
        columns={columns}
        getRowId={(row) => String(row.id)}
        pageSize={DEFAULT_PAGE_SIZE}
        query={searchTerm}
        draggable={canReorder ? { onReorder: handleReorder } : undefined}
        emptyState={
          <IllustrationContent
            illustration={SvgNoResult}
            title={t("emptyState.title")}
            description={t("emptyState.description")}
          />
        }
        footer={{}}
      />
    </div>
  );
}
