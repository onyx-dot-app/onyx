"use client";

import { useMemo, useState } from "react";
import DataTable from "@/refresh-components/table/DataTable";
import { createTableColumns } from "@/refresh-components/table/columns";
import { Content } from "@opal/layouts";
import { USER_ROLE_LABELS, UserRole } from "@/lib/types";
import { timeAgo } from "@/lib/time";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import useAdminUsers from "@/hooks/useAdminUsers";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { SvgUser, SvgUsers, SvgSlack } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import UserFilters from "./UserFilters";
import type { UserRow, UserGroupInfo, StatusFilter } from "./interfaces";
import { getInitials } from "./utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 8;

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
// Column renderers
// ---------------------------------------------------------------------------

function renderNameColumn(email: string, row: UserRow) {
  return (
    <Content
      sizePreset="main-ui"
      variant="section"
      title={row.personal_name ?? email}
      description={row.personal_name ? email : undefined}
    />
  );
}

function renderGroupsColumn(groups: UserGroupInfo[]) {
  if (!groups.length) {
    return (
      <Text as="span" secondaryBody text03>
        {"\u2014"}
      </Text>
    );
  }
  const visible = groups.slice(0, 2);
  const overflow = groups.length - visible.length;
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
}

function renderRoleColumn(role: UserRole) {
  const Icon = ROLE_ICONS[role];
  return (
    <div className="flex items-center gap-1.5">
      {Icon && <Icon size={14} className="text-text-03 shrink-0" />}
      <Text as="span" mainUiBody text03>
        {USER_ROLE_LABELS[role] ?? role}
      </Text>
    </div>
  );
}

function renderStatusColumn(isActive: boolean, row: UserRow) {
  return (
    <div className="flex flex-col">
      <Text as="span" mainUiBody text03>
        {isActive ? "Active" : "Inactive"}
      </Text>
      {row.is_scim_synced && (
        <Text as="span" secondaryBody text03>
          SCIM synced
        </Text>
      )}
    </div>
  );
}

function renderLastUpdatedColumn(value: string) {
  return (
    <Text as="span" secondaryBody text03>
      {timeAgo(value) ?? "\u2014"}
    </Text>
  );
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
    header: "Name",
    weight: 22,
    minWidth: 140,
    cell: renderNameColumn,
  }),
  tc.column("groups", {
    header: "Groups",
    weight: 24,
    minWidth: 200,
    cell: renderGroupsColumn,
  }),
  tc.column("role", {
    header: "Account Type",
    weight: 16,
    minWidth: 180,
    cell: renderRoleColumn,
  }),
  tc.column("is_active", {
    header: "Status",
    weight: 15,
    minWidth: 100,
    cell: renderStatusColumn,
  }),
  tc.column("updated_at", {
    header: "Last Updated",
    weight: 14,
    minWidth: 100,
    cell: renderLastUpdatedColumn,
  }),
  tc.actions(),
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function UsersTable() {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedRoles, setSelectedRoles] = useState<UserRole[]>([]);
  const [selectedStatus, setSelectedStatus] = useState<StatusFilter>("all");

  const { users, isLoading, error } = useAdminUsers();

  const filteredUsers = useMemo(() => {
    let result = users;

    if (selectedRoles.length > 0) {
      result = result.filter((u) => selectedRoles.includes(u.role));
    }

    if (selectedStatus === "active") {
      result = result.filter((u) => u.is_active);
    } else if (selectedStatus === "inactive") {
      result = result.filter((u) => !u.is_active);
    }

    return result;
  }, [users, selectedRoles, selectedStatus]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <SimpleLoader className="h-6 w-6" />
      </div>
    );
  }

  if (error) {
    return (
      <Text as="p" secondaryBody text03>
        Failed to load users. Please try refreshing the page.
      </Text>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <InputTypeIn
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        placeholder="Search users..."
        leftSearchIcon
      />
      <UserFilters
        selectedRoles={selectedRoles}
        onRolesChange={setSelectedRoles}
        selectedStatus={selectedStatus}
        onStatusChange={setSelectedStatus}
      />
      <DataTable
        data={filteredUsers}
        columns={columns}
        getRowId={(row) => row.id}
        pageSize={PAGE_SIZE}
        searchTerm={searchTerm}
        footer={{ mode: "summary" }}
      />
    </div>
  );
}
