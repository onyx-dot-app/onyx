"use client";

import { useMemo, useState } from "react";
import { Table, createTableColumns } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
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

function renderCreatedByColumn(_value: MinimalUserSnapshot | null, row: Agent) {
  return (
    <Content
      sizePreset="main-ui"
      variant="section"
      icon={SvgUser}
      title={row.builtin_persona ? "System" : (row.owner?.email ?? "—")}
    />
  );
}

function getAccessTitle(row: Agent): string {
  if (row.is_public) return "Public";
  if (row.groups.length > 0 || row.users.length > 0) return "Shared";
  return "Private";
}

function renderAccessColumn(_isPublic: boolean, row: Agent) {
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

const tc = createTableColumns<Agent>();

function buildColumns(onMutate: () => void) {
  return [
    tc.qualifier({
      content: "icon",
      background: true,
      getContent: (row) => (props) => (
        <AgentAvatar agent={row as unknown as MinimalAgent} size={props.size} />
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
          {value || "—"}
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

  const { agents, isLoading, refresh } = useAdminAgents();

  const columns = useMemo(() => buildColumns(refresh), [refresh]);

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
            title="No agents found"
            description="No agents match the current search."
          />
        }
        footer={{}}
      />
    </div>
  );
}
