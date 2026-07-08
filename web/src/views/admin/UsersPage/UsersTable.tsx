"use client";

import { useMemo, useState } from "react";
import { Table, createTableColumns } from "@opal/components";
import { Content } from "@opal/layouts";
import { Button } from "@opal/components";
import { SvgDownload, SvgSimpleLoader } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import { IllustrationContent } from "@opal/layouts";
import { UserRole, UserStatus, USER_STATUS_LABELS } from "@/lib/types";
import { timeAgo } from "@opal/time";
import Text from "@/refresh-components/texts/Text";
import { InputTypeIn } from "@opal/components";
import { toast } from "@/hooks/useToast";
import useAdminUsers from "@/hooks/useAdminUsers";
import { useSettings } from "@/lib/settings/hooks";
import useGroups from "@/hooks/useGroups";
import { downloadUsersCsv } from "./svc";
import UserFilters from "./UserFilters";
import { setUsersCraftAccess } from "./svc";
import GroupsCell from "./GroupsCell";
import UserRowActions from "./UserRowActions";
import UserRoleCell from "./UserRoleCell";
import type {
  UserRow,
  GroupOption,
  StatusFilter,
  StatusCountMap,
} from "./interfaces";
import UserAvatar from "@/refresh-components/avatars/UserAvatar";
import type { User } from "@/lib/types";

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

function renderStatusColumn(
  value: UserStatus,
  row: UserRow,
  craftAvailable: boolean
) {
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
      {craftAvailable && row.craft_enabled !== null && (
        <Text as="span" secondaryBody text03>
          {row.craft_enabled ? "Craft enabled" : "Craft disabled"}
        </Text>
      )}
    </div>
  );
}

function renderLastUpdatedColumn(value: string | null) {
  return (
    <Text as="span" secondaryBody text03>
      {value ? (timeAgo(value) ?? "\u2014") : "\u2014"}
    </Text>
  );
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<UserRow>();

function buildColumns(onMutate: () => void, craftAvailable: boolean) {
  return [
    tc.qualifier({
      content: "icon",
      iconSize: "lg",
      getContent: (row) => {
        const user = {
          email: row.email,
          personalization: row.personal_name
            ? { name: row.personal_name }
            : undefined,
        } as User;
        return (props) => <UserAvatar user={user} size={props.size} />;
      },
    }),
    tc.column("email", {
      header: "Name",
      weight: 22,
      cell: renderNameColumn,
    }),
    tc.column("groups", {
      header: "Groups",
      weight: 24,
      enableSorting: false,
      cell: (value, row) => (
        <GroupsCell groups={value} user={row} onMutate={onMutate} />
      ),
    }),
    tc.column("role", {
      header: "Account Type",
      weight: 16,
      cell: (_value, row) => <UserRoleCell user={row} onMutate={onMutate} />,
    }),
    tc.column("status", {
      header: "Status",
      weight: 14,
      cell: (value, row) => renderStatusColumn(value, row, craftAvailable),
    }),
    tc.column("updated_at", {
      header: "Last Updated",
      weight: 14,
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
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);

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

  const settings = useSettings();
  const craftAvailable = settings?.onyx_craft_available === true;

  const columns = useMemo(
    () => buildColumns(refresh, craftAvailable),
    [refresh, craftAvailable]
  );

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

  // Bulk Craft actions apply only to real users (invited/requested rows
  // have no user id yet).
  const selectedEmails = useMemo(() => {
    const ids = new Set(selectedRowIds);
    return filteredUsers
      .filter((u) => u.id !== null && ids.has(u.id))
      .map((u) => u.email);
  }, [filteredUsers, selectedRowIds]);

  const applyBulkCraftAccess = (
    craftEnabled: boolean | null,
    message: string
  ) => {
    void (async () => {
      try {
        await setUsersCraftAccess(selectedEmails, craftEnabled);
        refresh();
        toast.success(message);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "An error occurred");
      }
    })();
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <SvgSimpleLoader className="h-6 w-6" />
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

  const csvButton = (
    <Button
      icon={SvgDownload}
      prominence="tertiary"
      size="sm"
      tooltip="Download CSV"
      aria-label="Download CSV"
      onClick={() => {
        downloadUsersCsv().catch((err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to download CSV"
          );
        });
      }}
    />
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <div className="flex-1">
          <InputTypeIn
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search users..."
            searchIcon
          />
        </div>
        {craftAvailable && csvButton}
      </div>
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
      {craftAvailable && selectedEmails.length > 0 && (
        <div className="flex items-center gap-2">
          <Text as="span" secondaryBody text03>
            Craft access for {selectedEmails.length} selected:
          </Text>
          <Button
            prominence="secondary"
            size="sm"
            onClick={() =>
              applyBulkCraftAccess(
                true,
                `Craft enabled for ${selectedEmails.length} users`
              )
            }
          >
            Enable
          </Button>
          <Button
            prominence="secondary"
            size="sm"
            onClick={() =>
              applyBulkCraftAccess(
                false,
                `Craft disabled for ${selectedEmails.length} users`
              )
            }
          >
            Disable
          </Button>
          <Button
            prominence="tertiary"
            size="sm"
            onClick={() =>
              applyBulkCraftAccess(
                null,
                `Craft access reset for ${selectedEmails.length} users`
              )
            }
          >
            Use Default
          </Button>
        </div>
      )}
      <Table
        data={filteredUsers}
        columns={columns}
        getRowId={(row) => row.id ?? row.email}
        pageSize={PAGE_SIZE}
        searchTerm={searchTerm}
        selectionBehavior={craftAvailable ? "multi-select" : "no-select"}
        onSelectionChange={setSelectedRowIds}
        emptyState={
          <IllustrationContent
            illustration={SvgNoResult}
            title="No users found"
            description="No users match the current filters."
          />
        }
        footer={craftAvailable ? {} : { leftExtra: csvButton }}
      />
    </div>
  );
}
