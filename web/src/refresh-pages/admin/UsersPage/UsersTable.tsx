"use client";

import { useMemo, useState } from "react";
import DataTable from "@/refresh-components/table/DataTable";
import { createTableColumns } from "@/refresh-components/table/columns";
import { Content } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { IllustrationContent } from "@opal/layouts";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { UserRole, UserStatus, USER_STATUS_LABELS } from "@/lib/types";
import { timeAgo } from "@/lib/time";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import useAdminUsers from "@/hooks/useAdminUsers";
import useGroups from "@/hooks/useGroups";
import UserFilters from "./UserFilters";
import UserRowActions from "./UserRowActions";
import UserRoleCell from "./UserRoleCell";
import type {
  UserRow,
  UserGroupInfo,
  GroupOption,
  StatusFilter,
  StatusCountMap,
} from "./interfaces";
import { getInitials } from "./utils";

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

function renderStatusColumn(value: UserStatus, row: UserRow) {
  return (
    <div className="flex flex-col">
      <Text as="span" mainUiBody text03>
        {USER_STATUS_LABELS[value] ?? value}
      </Text>
      {row.is_scim_synced && (
        <Text as="span" secondaryBody text03>
          SCIM synced
        </Text>
      )}
    </div>
  );
}

function renderLastUpdatedColumn(value: string | null) {
  return (
    <Text as="span" secondaryBody text03>
      {timeAgo(value) ?? "\u2014"}
    </Text>
  );
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<UserRow>();

function buildColumns(onMutate: () => void) {
  return [
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
      enableSorting: false,
      cell: renderGroupsColumn,
    }),
    tc.column("role", {
      header: "Account Type",
      weight: 16,
      minWidth: 180,
      cell: (_value, row) => <UserRoleCell user={row} onMutate={onMutate} />,
    }),
    tc.column("status", {
      header: "Status",
      weight: 14,
      minWidth: 100,
      cell: renderStatusColumn,
    }),
    tc.column("updated_at", {
      header: "Last Updated",
      weight: 14,
      minWidth: 100,
      cell: renderLastUpdatedColumn,
    }),
    tc.actions({
      cell: (row) => <UserRowActions user={row} onMutate={onMutate} />,
    }),
  ];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 8;

interface UsersTableProps {
  selectedStatuses: StatusFilter;
  onStatusesChange: (statuses: StatusFilter) => void;
  roleCounts: Record<string, number>;
  statusCounts: StatusCountMap;
}

export default function UsersTable({
  selectedStatuses,
  onStatusesChange,
  roleCounts,
  statusCounts,
}: UsersTableProps) {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedRoles, setSelectedRoles] = useState<UserRole[]>([]);
  const [selectedGroups, setSelectedGroups] = useState<number[]>([]);

  const { data: allGroups } = useGroups();

  const groupOptions: GroupOption[] = useMemo(
    () =>
      (allGroups ?? []).map((g) => ({
        id: g.id,
        name: g.name,
        memberCount: g.users.length,
      })),
    [allGroups]
  );

  const { users, isLoading, error, refresh } = useAdminUsers();

  const columns = useMemo(() => buildColumns(refresh), [refresh]);

  // Client-side filtering
  const filteredUsers = useMemo(() => {
    let result = users;

    if (selectedRoles.length > 0) {
      result = result.filter(
        (u) => u.role !== null && selectedRoles.includes(u.role)
      );
    }

    if (selectedStatuses.length > 0) {
      result = result.filter((u) => selectedStatuses.includes(u.status));
    }

    if (selectedGroups.length > 0) {
      result = result.filter((u) =>
        u.groups.some((g) => selectedGroups.includes(g.id))
      );
    }

    return result;
  }, [users, selectedRoles, selectedStatuses, selectedGroups]);

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
        selectedGroups={selectedGroups}
        onGroupsChange={setSelectedGroups}
        groups={groupOptions}
        selectedStatuses={selectedStatuses}
        onStatusesChange={onStatusesChange}
        roleCounts={roleCounts}
        statusCounts={statusCounts}
      />
      {filteredUsers.length === 0 ? (
        <IllustrationContent
          illustration={SvgNoResult}
          title="No users found"
          description="No users match the current filters."
        />
      ) : (
        <DataTable
          data={filteredUsers}
          columns={columns}
          getRowId={(row) => row.id ?? row.email}
          pageSize={PAGE_SIZE}
          searchTerm={searchTerm}
          footer={{ mode: "summary" }}
        />
      )}
    </div>
  );
}
