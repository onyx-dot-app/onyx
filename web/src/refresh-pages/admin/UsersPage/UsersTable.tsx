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
import { timeAgo } from "@/lib/time";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UserGroupInfo {
  id: number;
  name: string;
}

interface UserRow {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  personal_name: string | null;
  created_at: string;
  updated_at: string;
  groups: UserGroupInfo[];
}

interface PaginatedResponse {
  items: UserRow[];
  total_items: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getInitials(name: string | null, email: string): string {
  if (name) {
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) {
      return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase();
    }
    return name.slice(0, 2).toUpperCase();
  }
  const local = email.split("@")[0];
  if (!local) return "?";
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
    getInitials: (row) => getInitials(row.personal_name, row.email),
    selectable: false,
  }),
  tc.column("email", {
    header: "User",
    weight: 25,
    minWidth: 180,
    cell: (value, row) =>
      row.personal_name ? (
        <div className="flex flex-col">
          <Text as="span" mainUiAction text04>
            {row.personal_name}
          </Text>
          <Text as="span" secondaryBody text03>
            {value}
          </Text>
        </div>
      ) : (
        <Content
          sizePreset="main-ui"
          variant="body"
          title={value}
          prominence="default"
        />
      ),
  }),
  tc.column("groups", {
    header: "Groups",
    weight: 20,
    minWidth: 120,
    cell: (value: UserGroupInfo[]) => {
      if (!value.length) {
        return (
          <Text as="span" secondaryBody text03>
            —
          </Text>
        );
      }
      const visible = value.slice(0, 2);
      const overflow = value.length - visible.length;
      return (
        <div className="flex items-center gap-1 flex-wrap">
          {visible.map((g) => (
            <Tag key={g.id} title={g.name} />
          ))}
          {overflow > 0 && (
            <Text as="span" secondaryBody text03>
              +{overflow}
            </Text>
          )}
        </div>
      );
    },
  }),
  tc.column("role", {
    header: "Account Type",
    weight: 18,
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
    weight: 15,
    minWidth: 100,
    cell: (value) => (
      <Tag title={statusLabel(value)} color={statusColor(value)} />
    ),
  }),
  tc.column("updated_at", {
    header: "Last Updated",
    weight: 14,
    minWidth: 100,
    cell: (value) => (
      <Text as="span" secondaryBody text03>
        {timeAgo(value) ?? "—"}
      </Text>
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
