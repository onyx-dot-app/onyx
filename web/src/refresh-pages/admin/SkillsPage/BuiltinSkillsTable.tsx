"use client";

import { useMemo } from "react";
import { Table, Tag, createTableColumns } from "@opal/components";
import { Content } from "@opal/layouts";
import { SvgBlocks } from "@opal/icons";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import type { BuiltinSkill } from "@/refresh-pages/admin/SkillsPage/interfaces";
import { DEFAULT_PAGE_SIZE } from "@/lib/constants";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface BuiltinSkillsTableProps {
  skills: BuiltinSkill[];
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<BuiltinSkill>();

const COLUMNS = [
  tc.qualifier({
    content: "icon",
    background: true,
    getContent: () => SvgBlocks,
  }),
  tc.column("name", {
    header: "Name",
    weight: 22,
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
    weight: 50,
    cell: (value) => (
      <Truncated mainUiBody text03>
        {value}
      </Truncated>
    ),
  }),
  tc.column("is_available", {
    header: "Status",
    weight: 28,
    cell: (isAvailable, row) =>
      isAvailable ? (
        <Tag title="Available" color="green" />
      ) : (
        <div className="flex flex-col gap-0.5">
          <Tag title="Unavailable" color="amber" />
          {row.unavailable_reason && (
            <Text as="span" secondaryBody text03>
              {row.unavailable_reason}
            </Text>
          )}
        </div>
      ),
  }),
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function BuiltinSkillsTable({
  skills,
}: BuiltinSkillsTableProps) {
  const columns = useMemo(() => COLUMNS, []);

  return (
    <Table
      data={skills}
      columns={columns}
      getRowId={(row) => row.slug}
      pageSize={DEFAULT_PAGE_SIZE}
    />
  );
}
