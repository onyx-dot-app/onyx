"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Table, createTableColumns } from "@opal/components";
import { Content, IllustrationContent, toast } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import Text from "@/refresh-components/texts/Text";
import { PageLoader } from "@opal/layouts";
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

const tc = createTableColumns<Agent>();

/** Typographic placeholder for a blank cell. */
const BLANK_CELL = "—";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AgentsTable() {
  const t = useTranslations("admin.agents");
  const [searchTerm, setSearchTerm] = useState("");

  const { agents, isLoading, refresh } = useAdminAgents();

  const columns = useMemo(() => {
    function renderCreatedByColumn(
      _value: MinimalUserSnapshot | null,
      row: Agent
    ) {
      return (
        <Content
          sizePreset="main-ui"
          variant="section"
          icon={SvgUser}
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
      tc.qualifier({
        content: "icon",
        background: true,
        getContent: (row) => (props) => (
          <AgentAvatar agent={row} size={props.size} />
        ),
      }),
      tc.column("name", {
        header: t("table.nameColumn.header"),
        weight: 25,
        cell: (value) => (
          <Text as="span" mainUiBody text05>
            {value}
          </Text>
        ),
      }),
      tc.column("description", {
        header: t("table.descriptionColumn.header"),
        weight: 35,
        cell: (value) => (
          <Text as="span" mainUiBody text03>
            {value || BLANK_CELL}
          </Text>
        ),
      }),
      tc.column("owner", {
        header: t("table.createdByColumn.header"),
        weight: 20,
        cell: renderCreatedByColumn,
      }),
      tc.column("is_public", {
        header: t("table.accessColumn.header"),
        weight: 12,
        cell: renderAccessColumn,
      }),
      tc.actions({
        cell: (row) => <AgentRowActions agent={row} onMutate={refresh} />,
      }),
    ];
  }, [refresh, t]);

  const nonBuiltinAgents = useMemo(
    () => agents.filter((p) => !p.builtin_persona),
    [agents]
  );

  const { filtered: filteredAgents, filterBar } =
    useAgentsFilters(nonBuiltinAgents);

  const canReorder = nonBuiltinAgents.some((agent) => can(agent, "reorder"));

  async function handleReorder(
    _orderedIds: string[],
    changedOrders: Record<string, number>
  ) {
    try {
      await updateAgentDisplayPriorities(changedOrders);
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
        data={filteredAgents}
        columns={columns}
        getRowId={(row) => String(row.id)}
        pageSize={DEFAULT_PAGE_SIZE}
        searchTerm={searchTerm}
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
