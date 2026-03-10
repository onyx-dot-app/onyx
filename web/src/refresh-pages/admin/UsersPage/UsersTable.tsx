"use client";

import { useState } from "react";
import type { SortingState } from "@tanstack/react-table";
import DataTable from "@/refresh-components/table/DataTable";
import { createTableColumns } from "@/refresh-components/table/columns";
import { Content } from "@opal/layouts";
import { USER_ROLE_LABELS, UserRole } from "@/lib/types";
import { timeAgo } from "@/lib/time";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import useAdminUsers from "@/hooks/useAdminUsers";
import { SvgUser, SvgUsers, SvgSlack } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import type { UserRow } from "./interfaces";

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

const ROLE_ICONS: Record<UserRole, IconFunctionComponent> = {
  [UserRole.BASIC]: SvgUser,
  [UserRole.ADMIN]: SvgUser,
  [UserRole.GLOBAL_CURATOR]: SvgUsers,
  [UserRole.CURATOR]: SvgUsers,
  [UserRole.LIMITED]: SvgUser,
  [UserRole.EXT_PERM_USER]: SvgUser,
  [UserRole.SLACK_USER]: SvgSlack,
};

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
    header: "Name",
    weight: 22,
    minWidth: 140,
    cell: (value, row) => (
      <Content
        sizePreset="main-ui"
        variant="section"
        title={row.personal_name ?? value}
        description={row.personal_name ? value : undefined}
      />
    ),
  }),
  tc.column("groups", {
    header: "Groups",
    weight: 20,
    minWidth: 180,
    cell: (value) => {
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
        <div className="flex items-center gap-1 flex-nowrap overflow-hidden min-w-0">
          {visible.map((g) => (
            <span
              key={g.id}
              className="inline-flex items-center flex-shrink-0 rounded-md bg-background-tint-02 px-2 py-0.5 whitespace-nowrap"
            >
              <Text as="span" secondaryBody text03>
                {g.name}
              </Text>
            </span>
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
    weight: 16,
    minWidth: 180,
    cell: (value) => {
      const Icon = ROLE_ICONS[value];
      return (
        <div className="flex items-center gap-1.5">
          {Icon && <Icon size={14} className="text-text-03 shrink-0" />}
          <Text as="span" mainUiBody text03>
            {USER_ROLE_LABELS[value] ?? value}
          </Text>
        </div>
      );
    },
  }),
  tc.column("is_active", {
    header: "Status",
    weight: 15,
    minWidth: 100,
    cell: (value, row) => (
      <div className="flex flex-col">
        <Text as="span" mainUiBody text03>
          {value ? "Active" : "Inactive"}
        </Text>
        {row.is_scim_synced && (
          <Text as="span" secondaryBody text03>
            SCIM synced
          </Text>
        )}
      </div>
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

const PAGE_SIZE = 8;

export default function UsersTable() {
  const [searchTerm, setSearchTerm] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [pageIndex, setPageIndex] = useState(0);

  const { users, totalItems, isLoading } = useAdminUsers({
    pageIndex,
    pageSize: PAGE_SIZE,
    searchTerm: searchTerm || undefined,
  });

  return (
    <div className="flex flex-col gap-3">
      <InputTypeIn
        value={searchTerm}
        onChange={(e) => {
          setSearchTerm(e.target.value);
          setPageIndex(0);
        }}
        placeholder="Search users..."
        leftSearchIcon
      />
      <DataTable
        data={users}
        columns={columns}
        getRowId={(row) => row.id}
        pageSize={PAGE_SIZE}
        searchTerm={searchTerm}
        footer={{ mode: "summary" }}
        serverSide={{
          totalItems,
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
