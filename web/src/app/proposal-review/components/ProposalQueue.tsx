"use client";

import { useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Text, Tag, Table } from "@opal/components";
import { createTableColumns } from "@opal/components/table/columns";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import InputSearch from "@/refresh-components/inputs/InputSearch";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Button } from "@opal/components/buttons/button/components";
import { useProposals } from "@/app/proposal-review/hooks/useProposals";
import type { Proposal, ProposalStatus } from "@/app/proposal-review/types";
import type { TagColor } from "@opal/components";

// ---------------------------------------------------------------------------
// Status configuration
// ---------------------------------------------------------------------------

const STATUS_TAG: Record<ProposalStatus, { color: TagColor; label: string }> = {
  PENDING: { color: "gray", label: "Pending" },
  IN_REVIEW: { color: "blue", label: "In Review" },
  APPROVED: { color: "green", label: "Approved" },
  CHANGES_REQUESTED: { color: "amber", label: "Changes Requested" },
  REJECTED: { color: "amber", label: "Rejected" },
};

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "ALL", label: "All statuses" },
  { value: "PENDING", label: "Pending" },
  { value: "IN_REVIEW", label: "In Review" },
  { value: "APPROVED", label: "Approved" },
  { value: "CHANGES_REQUESTED", label: "Changes Requested" },
  { value: "REJECTED", label: "Rejected" },
];

// Keys that are used for fixed columns or are internal — not shown as dynamic columns
const RESERVED_KEYS = new Set([
  "jira_key",
  "title",
  "link",
  "key",
  "status",
  "project",
  "project_name",
  "issuetype",
  "priority",
  "created",
  "updated",
  "reporter",
  "reporter_email",
  "Rank",
  "resolution",
  "resolution_date",
  "[CHART] Time in Status",
]);

// Jira statuses that mean "finished" — excluded by the default "Open" filter
const DONE_STATUSES = new Set(["Done", "Closed", "Resolved"]);

// Keys to show by default when no prior column visibility state exists
const DEFAULT_VISIBLE_KEYS = new Set([
  "PI Name",
  "Sponsor",
  "Sponsor Deadline",
  "Review Team",
]);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isDateLike(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}/.test(value);
}

function formatCellValue(value: string | string[] | undefined): string {
  if (value === undefined || value === null) return "--";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const tc = createTableColumns<Proposal>();

export default function ProposalQueue() {
  const router = useRouter();
  const { proposals, isLoading, error, configMissing } = useProposals();

  const [reviewFilter, setReviewFilter] = useState("ALL");
  const [jiraStatusFilter, setJiraStatusFilter] = useState("OPEN");
  const [searchQuery, setSearchQuery] = useState("");

  // Discover unique Jira ticket statuses from the data
  const jiraStatuses = useMemo(() => {
    const statuses = new Set<string>();
    for (const p of proposals) {
      const s = p.metadata.status;
      if (typeof s === "string" && s) statuses.add(s);
    }
    return Array.from(statuses).sort();
  }, [proposals]);

  // Discover all unique metadata keys across proposals (excluding reserved ones)
  const dynamicKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const p of proposals) {
      for (const k of Object.keys(p.metadata)) {
        if (!RESERVED_KEYS.has(k)) {
          keys.add(k);
        }
      }
    }
    return Array.from(keys).sort();
  }, [proposals]);

  // Build columns: fixed (Jira Key, Title) + dynamic + fixed (Status) + actions
  const columns = useMemo(() => {
    const cols = [
      tc.displayColumn({
        id: "jira_key",
        header: "Jira Key",
        width: { weight: 10, minWidth: 100 },
        cell: (row) => (
          <Text font="main-ui-body" color="text-04" nowrap>
            {row.metadata.jira_key ?? "--"}
          </Text>
        ),
      }),
      tc.displayColumn({
        id: "title",
        header: "Title",
        width: { weight: 25, minWidth: 150 },
        cell: (row) => (
          <Text font="main-ui-body" color="text-04">
            {row.metadata.title ?? "Untitled"}
          </Text>
        ),
      }),
      // Dynamic metadata columns
      ...dynamicKeys.map((key) =>
        tc.displayColumn({
          id: `meta_${key}`,
          header: key,
          width: { weight: 12, minWidth: 100 },
          cell: (row) => {
            const value = row.metadata[key];
            // Render dates with locale formatting
            if (typeof value === "string" && isDateLike(value)) {
              return (
                <Text font="main-ui-body" color="text-03" nowrap>
                  {new Date(value).toLocaleDateString()}
                </Text>
              );
            }
            return (
              <Text font="main-ui-body" color="text-03" nowrap>
                {formatCellValue(value)}
              </Text>
            );
          },
        })
      ),
      tc.displayColumn({
        id: "review_status",
        header: "Review",
        width: { weight: 10, minWidth: 120 },
        cell: (row) => {
          const statusConfig = STATUS_TAG[row.status];
          return (
            <Tag
              title={statusConfig.label}
              color={statusConfig.color}
              size="sm"
            />
          );
        },
      }),
      tc.actions({ showColumnVisibility: true }),
    ];
    return cols;
  }, [dynamicKeys]);

  // Load saved visibility from localStorage, falling back to defaults
  const STORAGE_KEY = "argus-queue-columns";

  const initialColumnVisibility = useMemo(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return JSON.parse(saved) as Record<string, boolean>;
    } catch {
      // ignore parse errors
    }
    // Default: show DEFAULT_VISIBLE_KEYS, hide the rest
    const vis: Record<string, boolean> = {};
    for (const key of dynamicKeys) {
      vis[`meta_${key}`] = DEFAULT_VISIBLE_KEYS.has(key);
    }
    return vis;
  }, [dynamicKeys]);

  const handleColumnVisibilityChange = useCallback(
    (visibility: Record<string, boolean>) => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(visibility));
      } catch {
        // localStorage full or unavailable — silently ignore
      }
    },
    []
  );

  // Filter proposals
  const filteredProposals = useMemo(() => {
    let result = proposals;

    // Jira ticket status filter
    if (jiraStatusFilter === "OPEN") {
      result = result.filter((p) => {
        const s =
          typeof p.metadata.status === "string" ? p.metadata.status : "";
        return !DONE_STATUSES.has(s);
      });
    } else if (jiraStatusFilter !== "ALL") {
      result = result.filter((p) => p.metadata.status === jiraStatusFilter);
    }

    // Review status filter
    if (reviewFilter !== "ALL") {
      result = result.filter((p) => p.status === reviewFilter);
    }

    // Search filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter((p) => {
        const m = p.metadata;
        return Object.values(m).some((v) => {
          if (!v) return false;
          const str = Array.isArray(v) ? v.join(" ") : String(v);
          return str.toLowerCase().includes(q);
        });
      });
    }

    return result;
  }, [proposals, jiraStatusFilter, reviewFilter, searchQuery]);

  function handleRowClick(proposal: Proposal) {
    router.push(`/proposal-review/proposals/${proposal.id}`);
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <SimpleLoader className="h-8 w-8" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-16 px-4">
        <IllustrationContent
          illustration={SvgNoResult}
          title="Failed to load proposals"
          description="Please try refreshing the page."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Filters row */}
      <div className="flex items-center gap-4 flex-nowrap">
        <div className="w-[280px] shrink-0">
          <InputSearch
            placeholder="Search proposals..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Text font="secondary-action" color="text-03">
            Ticket:
          </Text>
          <InputSelect
            value={jiraStatusFilter}
            onValueChange={setJiraStatusFilter}
          >
            <InputSelect.Trigger placeholder="Ticket Status" />
            <InputSelect.Content>
              <InputSelect.Group>
                <InputSelect.Item value="ALL">All</InputSelect.Item>
                <InputSelect.Item value="OPEN">Open</InputSelect.Item>
              </InputSelect.Group>
              <InputSelect.Separator />
              <InputSelect.Group>
                <InputSelect.Label>Jira Statuses</InputSelect.Label>
                {jiraStatuses.map((s) => (
                  <InputSelect.Item key={s} value={s}>
                    {s}
                  </InputSelect.Item>
                ))}
              </InputSelect.Group>
            </InputSelect.Content>
          </InputSelect>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Text font="secondary-action" color="text-03">
            Review:
          </Text>
          <InputSelect value={reviewFilter} onValueChange={setReviewFilter}>
            <InputSelect.Trigger placeholder="Review Status" />
            <InputSelect.Content>
              {STATUS_OPTIONS.map((opt) => (
                <InputSelect.Item key={opt.value} value={opt.value}>
                  {opt.label}
                </InputSelect.Item>
              ))}
            </InputSelect.Content>
          </InputSelect>
        </div>
      </div>

      {/* Empty state — config missing */}
      {filteredProposals.length === 0 && configMissing && (
        <div className="flex flex-col items-center justify-center gap-4 py-12">
          <IllustrationContent
            illustration={SvgNoResult}
            title="No proposals yet"
            description="Configure a Jira connector in Settings to start seeing proposals."
          />
          <Button
            href="/admin/proposal-review/settings"
            variant="default"
            prominence="primary"
          >
            Go to Settings
          </Button>
        </div>
      )}

      {/* Empty state — filtered or no data */}
      {filteredProposals.length === 0 && !configMissing && (
        <div className="flex items-center justify-center py-12">
          <IllustrationContent
            illustration={SvgNoResult}
            title="No proposals found"
            description={
              searchQuery ||
              reviewFilter !== "ALL" ||
              jiraStatusFilter !== "OPEN"
                ? "Try adjusting your search or filters."
                : "Proposals from Jira will appear here once synced."
            }
          />
        </div>
      )}

      {/* Table — wrapper adds pointer cursor since onRowClick doesn't set it */}
      {filteredProposals.length > 0 && (
        <div className="[&_.tbl-row]:cursor-pointer [&_.tbl-row:hover_td]:bg-background-tint-02">
          <Table
            key={dynamicKeys.join(",")}
            data={filteredProposals}
            getRowId={(row) => row.id}
            columns={columns}
            initialColumnVisibility={initialColumnVisibility}
            onColumnVisibilityChange={handleColumnVisibilityChange}
            onRowClick={(row) => handleRowClick(row)}
          />
        </div>
      )}
    </div>
  );
}
