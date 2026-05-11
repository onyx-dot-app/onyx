"use client";

import { useMemo, useState } from "react";
import { Table, Tag, createTableColumns } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import { SvgBlocks, SvgGlobe, SvgLock, SvgUser, SvgUsers } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import type { CustomSkill } from "@/refresh-pages/admin/SkillsPage/interfaces";
import {
  formatRelativeTime,
  summarizeVisibility,
} from "@/refresh-pages/admin/SkillsPage/helpers";
import { Section } from "@/layouts/general-layouts";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";
import CustomSkillRowActions from "@/refresh-pages/admin/SkillsPage/CustomSkillRowActions";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CustomSkillsTableProps {
  skills: CustomSkill[];
  /**
   * When true, the row actions menu shows admin-only actions
   * (promote / demote, disable any skill, delete any skill).
   */
  adminMode: boolean;
  /** Show the "Author" column. Hidden on the user-facing /skills page. */
  showAuthor?: boolean;
  /** Optional: override what the row "open" affordance does. */
  onOpenSkill?: (skill: CustomSkill) => void;
  /** Mutators (wireframe-only — no real backend). */
  onShareSkill?: (skill: CustomSkill) => void;
  onReplaceBundle?: (skill: CustomSkill) => void;
  onToggleEnabled?: (skill: CustomSkill) => void;
  onDeleteSkill?: (skill: CustomSkill) => void;
  onPromoteSkill?: (skill: CustomSkill) => void;
  onDemoteSkill?: (skill: CustomSkill) => void;
}

// ---------------------------------------------------------------------------
// Visibility cell
// ---------------------------------------------------------------------------

function VisibilityCell({ skill }: { skill: CustomSkill }) {
  const summary = summarizeVisibility(skill);
  const icon = (() => {
    switch (skill.visibility) {
      case "private":
        return SvgLock;
      case "users":
        return SvgUser;
      case "groups":
        return SvgUsers;
      case "users_and_groups":
        return SvgUsers;
      case "org_wide":
        return SvgGlobe;
    }
  })();

  return (
    <Content
      sizePreset="main-ui"
      variant="section"
      icon={icon}
      title={summary.label}
      description={summary.description}
    />
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CustomSkillsTable({
  skills,
  adminMode,
  showAuthor = true,
  onOpenSkill,
  onShareSkill,
  onReplaceBundle,
  onToggleEnabled,
  onDeleteSkill,
  onPromoteSkill,
  onDemoteSkill,
}: CustomSkillsTableProps) {
  const [searchTerm, setSearchTerm] = useState("");

  const columns = useMemo(() => {
    const tc = createTableColumns<CustomSkill>();

    const cols: ReturnType<
      typeof tc.column | typeof tc.qualifier | typeof tc.actions
    >[] = [
      tc.qualifier({
        content: "icon",
        background: true,
        getContent: () => SvgBlocks,
      }),
      tc.column("name", {
        header: "Name",
        weight: showAuthor ? 22 : 28,
        cell: (value, row) => (
          <Content
            sizePreset="main-ui"
            variant="section"
            title={value}
            description={row.slug}
          />
        ),
      }),
      tc.column("description", {
        header: "Description",
        weight: showAuthor ? 30 : 38,
        cell: (value) => (
          <Text as="span" mainUiBody text03>
            {value || "—"}
          </Text>
        ),
      }),
    ];

    if (showAuthor) {
      cols.push(
        tc.column("author", {
          header: "Author",
          weight: 16,
          cell: (author) => (
            <Content
              sizePreset="main-ui"
              variant="section"
              icon={SvgUser}
              title={author.name}
              description={author.is_admin ? "Admin" : "Member"}
            />
          ),
        })
      );
    }

    cols.push(
      tc.column("visibility", {
        header: "Visibility",
        weight: 16,
        cell: (_value, row) => <VisibilityCell skill={row} />,
      }),
      tc.column("updated_at", {
        header: "Updated",
        weight: 10,
        cell: (value, row) => (
          <div className="flex flex-col gap-0.5">
            <Text as="span" mainUiBody text03>
              {formatRelativeTime(value)}
            </Text>
            {!row.enabled && <Tag title="Disabled" color="amber" />}
            {row.promotion_requested && !row.promoted_by_admin && (
              <Tag title="Promotion requested" color="blue" />
            )}
          </div>
        ),
      }),
      tc.actions({
        cell: (row) => (
          <CustomSkillRowActions
            skill={row}
            adminMode={adminMode}
            onShare={() => onShareSkill?.(row)}
            onReplaceBundle={() => onReplaceBundle?.(row)}
            onToggleEnabled={() => onToggleEnabled?.(row)}
            onDelete={() => onDeleteSkill?.(row)}
            onPromote={() => onPromoteSkill?.(row)}
            onDemote={() => onDemoteSkill?.(row)}
            onOpen={() => onOpenSkill?.(row)}
          />
        ),
      })
    );

    return cols;
  }, [
    adminMode,
    showAuthor,
    onShareSkill,
    onReplaceBundle,
    onToggleEnabled,
    onDeleteSkill,
    onPromoteSkill,
    onDemoteSkill,
    onOpenSkill,
  ]);

  return (
    <Section gap={0.75} alignItems="stretch">
      <InputTypeIn
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        placeholder="Search skills..."
        leftSearchIcon
      />
      <Table
        data={skills}
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
