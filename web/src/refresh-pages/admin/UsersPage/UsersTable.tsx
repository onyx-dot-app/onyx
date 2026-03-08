"use client";

import { useState } from "react";
import useSWR from "swr";
import type { SortingState } from "@tanstack/react-table";
import DataTable from "@/refresh-components/table/DataTable";
import { createTableColumns } from "@/refresh-components/table/columns";
import { Content } from "@opal/layouts";
import { Tag } from "@opal/components";
import { UserRole, USER_ROLE_LABELS } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UserRow {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
}

interface PaginatedResponse {
  items: UserRow[];
  total_items: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getInitials(email: string): string {
  const local = email.split("@")[0];
  if (!local) return "?";
  // Try splitting on dots/underscores for multi-part names
  const parts = local.split(/[._-]/);
  if (parts.length >= 2) {
    return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  return local.slice(0, 2).toUpperCase();
}

function statusLabel(isActive: boolean): string {
  return isActive ? "Active" : "Inactive";
}

function statusColor(isActive: boolean): "green" | "gray" {
  return isActive ? "green" : "gray";
}

// ---------------------------------------------------------------------------
// Columns (stable reference — defined at module scope)
// ---------------------------------------------------------------------------

const tc = createTableColumns<UserRow>();

const columns = [
  tc.qualifier({
    content: "avatar-user",
    getInitials: (row) => getInitials(row.email),
    selectable: false,
  }),
  tc.column("email", {
    header: "User",
    weight: 35,
    minWidth: 180,
    cell: (value) => (
      <Content
        sizePreset="main-ui"
        variant="body"
        title={value}
        prominence="default"
      />
    ),
  }),
  tc.column("role", {
    header: "Account Type",
    weight: 25,
    minWidth: 120,
    cell: (value) => (
      <Content
        sizePreset="main-ui"
        variant="body"
        title={USER_ROLE_LABELS[value] ?? value}
        prominence="muted"
      />
    ),
  }),
  tc.column("is_active", {
    header: "Status",
    weight: 20,
    minWidth: 100,
    cell: (value) => (
      <Tag title={statusLabel(value)} color={statusColor(value)} />
    ),
  }),
  tc.actions(),
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 10;

export default function UsersTable() {
  const [searchTerm, setSearchTerm] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [pageIndex, setPageIndex] = useState(0);

  const queryParams = new URLSearchParams({
    page_num: String(pageIndex),
    page_size: String(PAGE_SIZE),
    ...(searchTerm && { q: searchTerm }),
  });

  const { data: response, isLoading } = useSWR<PaginatedResponse>(
    `/api/manage/users/accepted?${queryParams.toString()}`,
    errorHandlingFetcher
  );

  return (
    <div className="flex flex-col gap-3">
      <InputTypeIn
        value={searchTerm}
        onChange={(e) => {
          setSearchTerm(e.target.value);
          setPageIndex(0);
        }}
        placeholder="Search users by email..."
        leftSearchIcon
      />
      <DataTable
        data={response?.items ?? []}
        columns={columns}
        getRowId={(row) => row.id}
        pageSize={PAGE_SIZE}
        searchTerm={searchTerm}
        footer={{ mode: "summary" }}
        serverSide={{
          totalItems: response?.total_items ?? 0,
          isLoading,
          onSortingChange: setSorting,
          onPaginationChange: (idx) => {
            setPageIndex(idx);
          },
          onSearchTermChange: () => {
            // search state managed via searchTerm prop above
          },
        }}
      />
    </div>
  );
}
