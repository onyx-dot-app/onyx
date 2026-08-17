"use client";

import { useEffect, useMemo, useState } from "react";
import {
  InputSelect,
  InputTypeIn,
  Table,
  Text,
  createTableColumns,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgUser } from "@opal/icons";
import type { UsageExportTotals, UsageExportUser } from "@/lib/usage/userUsage";
import { formatCost, formatTokens } from "@/lib/utils";

const ALL = "__all__";

export interface SpendRow {
  email: string;
  cost_cents: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
}

function emptyTotals(): UsageExportTotals {
  return {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    cost_cents: 0,
  };
}

function filteredRow(
  user: UsageExportUser,
  model: string,
  flow: string
): SpendRow | null {
  if (model === ALL && flow === ALL) {
    return {
      email: user.email,
      ...user.totals,
      total_tokens: user.totals.input_tokens + user.totals.output_tokens,
    };
  }
  const records = user.records.filter(
    (record) =>
      (model === ALL || record.model === model) &&
      (flow === ALL || record.flow === flow)
  );
  if (records.length === 0) return null;
  const totals = records.reduce(
    (sum, record) => ({
      input_tokens: sum.input_tokens + record.input_tokens,
      output_tokens: sum.output_tokens + record.output_tokens,
      cache_read_tokens: sum.cache_read_tokens + record.cache_read_tokens,
      cache_creation_tokens:
        sum.cache_creation_tokens + record.cache_creation_tokens,
      cost_cents: sum.cost_cents + record.cost_cents,
    }),
    emptyTotals()
  );
  return {
    email: user.email,
    ...totals,
    total_tokens: totals.input_tokens + totals.output_tokens,
  };
}

const tc = createTableColumns<SpendRow>();

function buildColumns() {
  return [
    tc.qualifier({ content: "icon", getContent: () => SvgUser }),
    tc.column("email", {
      header: "User",
      weight: 38,
      cell: (value) => (
        <span className="underline-offset-2 group-hover/row:underline">
          <Text font="main-ui-body" color="text-05" nowrap>
            {value}
          </Text>
        </span>
      ),
    }),
    tc.column("cost_cents", {
      header: "Spend",
      weight: 16,
      alignment: "right",
      cell: (value) => (
        <span className="tabular-nums">
          <Text font="main-ui-action" color="text-05" nowrap>
            {formatCost(value)}
          </Text>
        </span>
      ),
    }),
    tc.column("total_tokens", {
      header: "Tokens",
      weight: 18,
      alignment: "right",
      cell: (value) => (
        <span className="tabular-nums">
          <Text font="main-ui-action" color="text-05" nowrap>
            {formatTokens(value)}
          </Text>
        </span>
      ),
    }),
    tc.column("input_tokens", {
      header: "Input",
      weight: 14,
      alignment: "right",
      cell: (value) => (
        <span className="tabular-nums">
          <Text font="main-ui-body" color="text-03" nowrap>
            {formatTokens(value)}
          </Text>
        </span>
      ),
    }),
    tc.column("output_tokens", {
      header: "Output",
      weight: 14,
      alignment: "right",
      cell: (value) => (
        <span className="tabular-nums">
          <Text font="main-ui-body" color="text-03" nowrap>
            {formatTokens(value)}
          </Text>
        </span>
      ),
    }),
  ];
}

const COLUMNS = buildColumns();

interface SpendByUserTableProps {
  users: UsageExportUser[];
  onSelectUser: (email: string) => void;
}

export default function SpendByUserTable({
  users,
  onSelectUser,
}: SpendByUserTableProps) {
  const [searchTerm, setSearchTerm] = useState("");
  const [model, setModel] = useState(ALL);
  const [flow, setFlow] = useState(ALL);

  const models = useMemo(
    () =>
      Array.from(
        new Set(
          users.flatMap((user) => user.records.map((record) => record.model))
        )
      ).sort(),
    [users]
  );
  const flows = useMemo(
    () =>
      Array.from(
        new Set(
          users.flatMap((user) =>
            user.records.flatMap((record) =>
              record.flow !== undefined ? [record.flow] : []
            )
          )
        )
      ).sort(),
    [users]
  );

  useEffect(() => {
    if (model !== ALL && !models.includes(model)) setModel(ALL);
  }, [model, models]);

  useEffect(() => {
    if (flow !== ALL && !flows.includes(flow)) setFlow(ALL);
  }, [flow, flows]);

  // Filtered manually: Table's built-in global filter matches any column, so numeric queries would match token counts too.
  const rows = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    return users.flatMap((user) => {
      if (query && !user.email.toLowerCase().includes(query)) return [];
      const row = filteredRow(user, model, flow);
      return row ? [row] : [];
    });
  }, [users, model, flow, searchTerm]);

  return (
    <Section
      flexDirection="column"
      justifyContent="start"
      alignItems="stretch"
      gap={2}
      width="full"
      height="fit"
    >
      {/* sm:flex-row / sm:items-center have no Section equivalent, kept as a raw div */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1 sm:max-w-72">
          <InputTypeIn
            value={searchTerm}
            placeholder="Search users by email…"
            aria-label="Search users by email"
            onChange={(event) => setSearchTerm(event.target.value)}
          />
        </div>
        <div className="flex w-full flex-col gap-2 sm:ml-auto sm:w-auto sm:flex-row">
          {models.length > 0 && (
            <div className="w-full sm:w-44">
              <InputSelect value={model} onValueChange={setModel}>
                <InputSelect.Trigger placeholder="All models" />
                <InputSelect.Content>
                  <InputSelect.Item value={ALL}>All models</InputSelect.Item>
                  {models.map((option) => (
                    <InputSelect.Item key={option} value={option}>
                      {option}
                    </InputSelect.Item>
                  ))}
                </InputSelect.Content>
              </InputSelect>
            </div>
          )}
          {flows.length > 0 && (
            <div className="w-full sm:w-40">
              <InputSelect value={flow} onValueChange={setFlow}>
                <InputSelect.Trigger placeholder="All flows" />
                <InputSelect.Content>
                  <InputSelect.Item value={ALL}>All flows</InputSelect.Item>
                  {flows.map((option) => (
                    <InputSelect.Item key={option} value={option}>
                      {option}
                    </InputSelect.Item>
                  ))}
                </InputSelect.Content>
              </InputSelect>
            </div>
          )}
        </div>
      </div>

      <Text font="secondary-body" color="text-03" aria-live="polite">
        {`${rows.length.toLocaleString()} ${rows.length === 1 ? "user" : "users"}`}
      </Text>

      <Table
        // Remount on filter change so the Table's internal page index resets;
        // otherwise a narrower `rows` can leave it stranded past the last page.
        key={`${model}-${flow}-${searchTerm}`}
        data={rows}
        columns={COLUMNS}
        getRowId={(row) => row.email}
        pageSize={10}
        initialSorting={[{ id: "cost_cents", desc: true }]}
        onRowClick={(row) => onSelectUser(row.email)}
        getRowLabel={(row) => `View usage details for ${row.email}`}
        footer={{}}
        emptyState={
          <Text font="main-ui-body" color="text-03">
            No usage matches the current filters.
          </Text>
        }
      />
    </Section>
  );
}
