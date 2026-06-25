"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Table, createTableColumns } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import Text from "@/refresh-components/texts/Text";
import { PageLoader } from "@/refresh-components/PageLoader";
import { InputTypeIn } from "@opal/components";
import type { MinimalUserSnapshot } from "@/lib/types";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import type { MinimalAgent, Agent } from "@/lib/agents/types";
import { useAdminAgents } from "@/lib/agents/hooks";
import { toast } from "@/hooks/useToast";
import AgentRowActions from "@/refresh-pages/admin/AgentsPage/AgentRowActions";
import { updateAgentDisplayPriorities } from "@/lib/agents/svc";
import { SvgUser } from "@opal/icons";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";
import { Section } from "@/layouts/general-layouts";
import { useAgentsFilters } from "@/sections/agents/AgentsFilters";

// ---------------------------------------------------------------------------
// Column renderers
// ---------------------------------------------------------------------------

function renderCreatedByColumn(
  t: TFunction,
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
          ? t("admin.agents.system")
          : (row.owner?.email ?? "—")
      }
    />
  );
}

function getAccessTitle(t: TFunction, row: Agent): string {
  if (row.is_public) return t("admin.agents.public");
  if (row.groups.length > 0 || row.users.length > 0 || row.owner_group) {
    return t("admin.agents.shared");
  }
  return t("admin.agents.private");
}

function renderAccessColumn(t: TFunction, _isPublic: boolean, row: Agent) {
  return (
    <Content
      sizePreset="main-ui"
      variant="section"
      title={getAccessTitle(t, row)}
      description={
        !row.is_listed
          ? t("admin.agents.unlisted")
          : row.is_featured
            ? t("admin.agents.featured")
            : undefined
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<Agent>();

function buildColumns(onMutate: () => void, t: TFunction) {
  return [
    tc.qualifier({
      content: "icon",
      background: true,
      getContent: (row) => (props) => (
        <AgentAvatar agent={row as unknown as MinimalAgent} size={props.size} />
      ),
    }),
    tc.column("name", {
      header: t("admin.agents.column_name"),
      weight: 25,
      cell: (value) => (
        <Text as="span" mainUiBody text05>
          {value}
        </Text>
      ),
    }),
    tc.column("description", {
      header: t("admin.agents.column_description"),
      weight: 35,
      cell: (value) => (
        <Text as="span" mainUiBody text03>
          {value || "—"}
        </Text>
      ),
    }),
    tc.column("owner", {
      header: t("admin.agents.column_created_by"),
      weight: 20,
      cell: (_value, row) => renderCreatedByColumn(t, _value, row),
    }),
    tc.column("is_public", {
      header: t("admin.agents.column_access"),
      weight: 12,
      cell: (_value, row) => renderAccessColumn(t, _value, row),
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
  const { t } = useTranslation();
  const [searchTerm, setSearchTerm] = useState("");

  const { agents, isLoading, refresh } = useAdminAgents();

  const columns = useMemo(() => buildColumns(refresh, t), [refresh, t]);

  const nonBuiltinAgents = useMemo(
    () => agents.filter((p) => !p.builtin_persona),
    [agents]
  );

  const { filtered: filteredAgents, filterBar } =
    useAgentsFilters(nonBuiltinAgents);

  async function handleReorder(
    _orderedIds: string[],
    changedOrders: Record<string, number>
  ) {
    try {
      await updateAgentDisplayPriorities(changedOrders);
      refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("admin.agents.reorder_failed")
      );
      refresh();
    }
  }

  if (isLoading) {
    return <PageLoader />;
  }

  return (
    <div className="flex flex-col">
      <Section gap={0.5}>
        <InputTypeIn
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder={t("admin.agents.search_placeholder")}
          searchIcon
        />
        <Section gap={0.25} flexDirection="row" justifyContent="start">
          {filterBar}
        </Section>
      </Section>
      <Table
        data={filteredAgents}
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
            title={t("admin.agents.no_agents")}
            description={t("admin.agents.no_agents_desc")}
          />
        }
        footer={{}}
      />
    </div>
  );
}
