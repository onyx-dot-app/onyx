"use client";

import { useState, useMemo } from "react";
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

// ---------------------------------------------------------------------------
// Deadline helpers
// ---------------------------------------------------------------------------

function getDeadlineInfo(deadline: string | undefined): {
  display: string;
  colorClass: string;
} {
  if (!deadline) return { display: "--", colorClass: "text-text-03" };

  const deadlineDate = new Date(deadline);
  const now = new Date();
  const diffMs = deadlineDate.getTime() - now.getTime();
  const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
  const display = deadlineDate.toLocaleDateString();

  if (diffDays < 0) return { display, colorClass: "text-status-error-03" };
  if (diffDays <= 7) return { display, colorClass: "text-status-warning-03" };
  return { display, colorClass: "text-status-success-03" };
}

// ---------------------------------------------------------------------------
// Table columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<Proposal>();

const proposalColumns = [
  tc.displayColumn({
    id: "jira_key",
    header: "Jira Key",
    width: { weight: 12, minWidth: 100 },
    cell: (row) => (
      <Text font="main-ui-body" color="text-01" nowrap>
        {row.metadata.jira_key ?? "--"}
      </Text>
    ),
  }),
  tc.displayColumn({
    id: "title",
    header: "Title",
    width: { weight: 25, minWidth: 150 },
    cell: (row) => (
      <Text font="main-ui-body" color="text-01">
        {row.metadata.title ?? "Untitled"}
      </Text>
    ),
  }),
  tc.displayColumn({
    id: "pi_name",
    header: "PI",
    width: { weight: 15, minWidth: 100 },
    cell: (row) => (
      <Text font="main-ui-body" color="text-02" nowrap>
        {row.metadata.pi_name ?? "--"}
      </Text>
    ),
  }),
  tc.displayColumn({
    id: "sponsor",
    header: "Sponsor",
    width: { weight: 15, minWidth: 100 },
    cell: (row) => (
      <Text font="main-ui-body" color="text-02" nowrap>
        {row.metadata.sponsor ?? "--"}
      </Text>
    ),
  }),
  tc.displayColumn({
    id: "deadline",
    header: "Deadline",
    width: { weight: 12, minWidth: 100 },
    cell: (row) => {
      const deadline = getDeadlineInfo(row.metadata.deadline);
      return (
        <span className={deadline.colorClass}>
          <Text font="main-ui-body" color="inherit" nowrap>
            {deadline.display}
          </Text>
        </span>
      );
    },
  }),
  tc.displayColumn({
    id: "status",
    header: "Status",
    width: { weight: 13, minWidth: 120 },
    cell: (row) => {
      const statusConfig = STATUS_TAG[row.status];
      return (
        <Tag title={statusConfig.label} color={statusConfig.color} size="sm" />
      );
    },
  }),
  tc.displayColumn({
    id: "officer",
    header: "Officer",
    width: { weight: 12, minWidth: 100 },
    cell: (row) => (
      <Text font="main-ui-body" color="text-02" nowrap>
        {row.metadata.officer ?? "--"}
      </Text>
    ),
  }),
  tc.actions({ showColumnVisibility: false, showSorting: false }),
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ProposalQueue() {
  const router = useRouter();
  const { proposals, isLoading, error, configMissing } = useProposals();

  const [statusFilter, setStatusFilter] = useState("ALL");
  const [searchQuery, setSearchQuery] = useState("");

  // Filter and sort proposals
  const filteredProposals = useMemo(() => {
    let result = proposals;

    // Status filter
    if (statusFilter !== "ALL") {
      result = result.filter((p) => p.status === statusFilter);
    }

    // Search filter (keyword match on title, PI, sponsor, jira key)
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter((p) => {
        const m = p.metadata;
        return (
          m.title?.toLowerCase().includes(q) ||
          m.pi_name?.toLowerCase().includes(q) ||
          m.sponsor?.toLowerCase().includes(q) ||
          m.jira_key?.toLowerCase().includes(q)
        );
      });
    }

    // Sort by deadline (soonest first, no deadline last)
    result = [...result].sort((a, b) => {
      const aDate = a.metadata.deadline
        ? new Date(a.metadata.deadline).getTime()
        : Infinity;
      const bDate = b.metadata.deadline
        ? new Date(b.metadata.deadline).getTime()
        : Infinity;
      return aDate - bDate;
    });

    return result;
  }, [proposals, statusFilter, searchQuery]);

  function handleRowClick(proposal: Proposal) {
    router.push(`/proposal-review/proposals/${proposal.id}`);
  }

  // --- Loading ---
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <SimpleLoader className="h-8 w-8" />
      </div>
    );
  }

  // --- Error ---
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
      <div className="flex items-center gap-3">
        <div className="flex-1 max-w-[320px]">
          <InputSearch
            placeholder="Search proposals..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <div className="w-[180px]">
          <InputSelect value={statusFilter} onValueChange={setStatusFilter}>
            <InputSelect.Trigger placeholder="Status" />
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
              searchQuery || statusFilter !== "ALL"
                ? "Try adjusting your search or filters."
                : "Proposals from Jira will appear here once synced."
            }
          />
        </div>
      )}

      {/* Table */}
      {filteredProposals.length > 0 && (
        <Table
          data={filteredProposals}
          getRowId={(row) => row.id}
          columns={proposalColumns}
          onRowClick={(row) => handleRowClick(row)}
        />
      )}
    </div>
  );
}
