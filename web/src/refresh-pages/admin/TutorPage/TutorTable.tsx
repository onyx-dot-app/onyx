"use client";

import { useMemo, useState } from "react";
import { Table, createTableColumns } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import type {
  MinimalPersonaSnapshot,
  Persona,
} from "@/app/admin/agents/interfaces";
import { useAdminPersonas } from "@/hooks/useAdminPersonas";
import { useUser } from "@/providers/UserProvider";
import type { TutorRow } from "./interfaces";
import TutorRowActions from "./TutorRowActions";
import {
  VIRTUAL_TUTOR_LABEL_NAME,
  TEACHING_STYLE_OPTIONS,
  detectTeachingStyle,
} from "./constants";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toTutorRow(persona: Persona): TutorRow {
  return {
    id: persona.id,
    name: persona.name,
    description: persona.description,
    is_public: persona.is_public,
    is_listed: persona.is_listed,
    owner: persona.owner,
    uploaded_image_id: persona.uploaded_image_id,
    icon_name: persona.icon_name,
    system_prompt: persona.system_prompt,
  };
}

function isTutor(persona: Persona): boolean {
  return (
    persona.labels?.some((l) => l.name === VIRTUAL_TUTOR_LABEL_NAME) ?? false
  );
}

// ---------------------------------------------------------------------------
// Column renderers
// ---------------------------------------------------------------------------

function renderStyleColumn(systemPrompt: string | null) {
  const style = detectTeachingStyle(systemPrompt);
  const option = TEACHING_STYLE_OPTIONS.find((o) => o.value === style);
  return (
    <Content
      sizePreset="main-ui"
      variant="section"
      title={option?.label ?? "Balanced"}
    />
  );
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<TutorRow>();

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
    tc.column("system_prompt", {
      header: "Teaching Style",
      weight: 15,
      cell: renderStyleColumn,
    }),
    tc.actions({
      cell: (row) => <TutorRowActions tutor={row} onMutate={onMutate} />,
    }),
  ];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 10;

export default function TutorTable() {
  const [searchTerm, setSearchTerm] = useState("");
  const { user } = useUser();

  const { personas, isLoading, error, refresh } = useAdminPersonas();

  const columns = useMemo(() => buildColumns(refresh), [refresh]);

  const tutorRows: TutorRow[] = useMemo(
    () =>
      personas
        .filter((p) => isTutor(p) && p.owner?.id === user?.id)
        .map(toTutorRow),
    [personas, user?.id]
  );

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <SimpleLoader className="h-6 w-6" />
      </div>
    );
  }

  if (error) {
    console.error("Failed to load tutors:", error);
    return (
      <Text as="p" secondaryBody text03>
        Failed to load tutors. Please try refreshing the page.
      </Text>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <InputTypeIn
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        placeholder="Search tutors..."
        leftSearchIcon
      />
      <Table
        data={tutorRows}
        columns={columns}
        getRowId={(row) => String(row.id)}
        pageSize={PAGE_SIZE}
        searchTerm={searchTerm}
        emptyState={
          <IllustrationContent
            illustration={SvgNoResult}
            title="No virtual tutors yet"
            description="Create your first virtual tutor to get started."
          />
        }
        footer={{}}
      />
    </div>
  );
}
