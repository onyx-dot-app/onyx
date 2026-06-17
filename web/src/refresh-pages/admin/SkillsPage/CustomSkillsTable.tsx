"use client";

import { useMemo, useState } from "react";
import { Table, createTableColumns } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import { SvgBlocks, SvgUser } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import { InputTypeIn } from "@opal/components";
import type { CustomSkill } from "@/refresh-pages/admin/SkillsPage/interfaces";
import { summarizeVisibility } from "@/refresh-pages/admin/SkillsPage/helpers";
import { Section } from "@/layouts/general-layouts";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";
import CustomSkillRowActions from "@/refresh-pages/admin/SkillsPage/CustomSkillRowActions";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CustomSkillsTableProps {
  skills: CustomSkill[];
  onShareSkill: (skill: CustomSkill) => void;
  onReplaceBundle: (skill: CustomSkill) => void;
  onToggleEnabled: (skill: CustomSkill) => void;
  onDeleteSkill: (skill: CustomSkill) => void;
}

// ---------------------------------------------------------------------------
// Column renderers
// ---------------------------------------------------------------------------

function renderCreatedByColumn(value: string | null) {
  return (
    <Content
      sizePreset="main-ui"
      variant="section"
      icon={SvgUser}
      title={value ?? "—"}
    />
  );
}

function renderAccessColumn(_value: boolean, row: CustomSkill) {
  const summary = summarizeVisibility(row);
  return (
    <Content
      sizePreset="main-ui"
      variant="section"
      title={summary.label}
      description={!row.enabled ? "Disabled" : summary.description}
    />
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CustomSkillsTable({
  skills,
  onShareSkill,
  onReplaceBundle,
  onToggleEnabled,
  onDeleteSkill,
}: CustomSkillsTableProps) {
  const [searchTerm, setSearchTerm] = useState("");

  const sortedSkills = useMemo(() => {
    // Group order: org-wide, then group-granted, then personal;
    // alphabetical by name within each group.
    const groupRank = (skill: CustomSkill): number => {
      if (skill.is_public) return 0;
      if (skill.is_personal) return 2;
      return 1;
    };
    return [...skills].sort(
      (a, b) =>
        groupRank(a) - groupRank(b) ||
        a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
    );
  }, [skills]);

  const columns = useMemo(() => {
    const tc = createTableColumns<CustomSkill>();

    return [
      tc.qualifier({
        content: "icon",
        background: true,
        getContent: () => SvgBlocks,
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
          <Truncated mainUiBody text03>
            {value || "—"}
          </Truncated>
        ),
      }),
      tc.column("author_email", {
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
        cell: (row) => (
          <CustomSkillRowActions
            skill={row}
            onShare={() => onShareSkill(row)}
            onReplaceBundle={() => onReplaceBundle(row)}
            onToggleEnabled={() => onToggleEnabled(row)}
            onDelete={() => onDeleteSkill(row)}
          />
        ),
      }),
    ];
  }, [onShareSkill, onReplaceBundle, onToggleEnabled, onDeleteSkill]);

  return (
    <Section gap={0.75} alignItems="stretch">
      <InputTypeIn
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        placeholder="Search skills..."
        searchIcon
      />
      <Table
        data={sortedSkills}
        columns={columns}
        getRowId={(row) => row.id}
        pageSize={DEFAULT_PAGE_SIZE}
        searchTerm={searchTerm}
        emptyState={
          <IllustrationContent
            illustration={SvgNoResult}
            title="No skills yet"
            description="Upload a zip bundle to add a custom skill."
          />
        }
        footer={{}}
      />
    </Section>
  );
}
