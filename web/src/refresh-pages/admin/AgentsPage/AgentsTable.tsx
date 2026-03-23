"use client";

import { useMemo, useState } from "react";
import { Table, createTableColumns } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Tag } from "@opal/components";
import type { MinimalUserSnapshot } from "@/lib/types";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import type { MinimalPersonaSnapshot } from "@/app/admin/agents/interfaces";
import { useAdminPersonas } from "@/hooks/useAdminPersonas";
import { toast } from "@/hooks/useToast";
import AgentRowActions from "@/refresh-pages/admin/AgentsPage/AgentRowActions";
import { updateAgentDisplayPriorities } from "@/refresh-pages/admin/AgentsPage/svc";
import type { AgentRow } from "@/refresh-pages/admin/AgentsPage/interfaces";
import type { Persona } from "@/app/admin/agents/interfaces";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toAgentRow(persona: Persona): AgentRow {
  return {
    id: persona.id,
    name: persona.name,
    description: persona.description,
    is_public: persona.is_public,
    is_visible: persona.is_visible,
    featured: persona.featured,
    builtin_persona: persona.builtin_persona,
    display_priority: persona.display_priority,
    owner: persona.owner,
    groups: persona.groups,
    users: persona.users,
    uploaded_image_id: persona.uploaded_image_id,
    icon_name: persona.icon_name,
  };
}

// ---------------------------------------------------------------------------
// Column renderers
// ---------------------------------------------------------------------------

function renderCreatedByColumn(
  _value: MinimalUserSnapshot | null,
  row: AgentRow
) {
  if (row.builtin_persona) {
    return (
      <Text as="span" mainUiBody text03>
        System
      </Text>
    );
  }
  return (
    <Text as="span" mainUiBody text03>
      {row.owner?.email ?? "\u2014"}
    </Text>
  );
}

function renderAccessColumn(isPublic: boolean) {
  return (
    <Tag
      color={isPublic ? "green" : "gray"}
      size="sm"
      title={isPublic ? "Public" : "Private"}
    />
  );
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<AgentRow>();

function buildColumns(onMutate: () => void) {
  return [
    tc.displayColumn({
      id: "avatar",
      cell: (row) => (
        <AgentAvatar
          agent={row as unknown as MinimalPersonaSnapshot}
          size={32}
        />
      ),
      width: { fixed: 48 },
      enableHiding: false,
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

  const { personas, isLoading, error, refresh } = useAdminPersonas();

  const columns = useMemo(() => buildColumns(refresh), [refresh]);

  const agentRows: AgentRow[] = useMemo(
    () => personas.filter((p) => !p.builtin_persona).map(toAgentRow),
    [personas]
  );

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
