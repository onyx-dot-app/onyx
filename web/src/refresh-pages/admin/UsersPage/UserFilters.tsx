"use client";

import { useState } from "react";
import { SvgCheck, SvgUser, SvgUserManage, SvgUsers } from "@opal/icons";
import { SvgSlack } from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";
import { FilterButton } from "@opal/components";
import Popover from "@/refresh-components/Popover";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import ShadowDiv from "@/refresh-components/ShadowDiv";
import {
  UserRole,
  UserStatus,
  USER_ROLE_LABELS,
  USER_STATUS_LABELS,
} from "@/lib/types";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import type { GroupOption, StatusFilter, StatusCountMap } from "./interfaces";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VISIBLE_FILTER_ROLES: UserRole[] = [
  UserRole.ADMIN,
  UserRole.GLOBAL_CURATOR,
  UserRole.BASIC,
  UserRole.SLACK_USER,
];

const FILTERABLE_ROLES = VISIBLE_FILTER_ROLES.map(
  (role) => [role, USER_ROLE_LABELS[role]] as [UserRole, string]
);

const FILTERABLE_STATUSES = (
  Object.entries(USER_STATUS_LABELS) as [UserStatus, string][]
).filter(
  ([value]) => value !== UserStatus.REQUESTED || NEXT_PUBLIC_CLOUD_ENABLED
);

const ROLE_ICONS: Partial<Record<UserRole, IconFunctionComponent>> = {
  [UserRole.ADMIN]: SvgUserManage,
  [UserRole.SLACK_USER]: SvgSlack,
};

/** Map UserStatus enum values to the keys returned by the counts endpoint. */
const STATUS_COUNT_KEY: Record<UserStatus, keyof StatusCountMap> = {
  [UserStatus.ACTIVE]: "active",
  [UserStatus.INACTIVE]: "inactive",
  [UserStatus.INVITED]: "invited",
  [UserStatus.REQUESTED]: "requested",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function CountBadge({ count }: { count: number | undefined }) {
  return (
    <Text as="span" secondaryBody text03>
      {count ?? 0}
    </Text>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface UserFiltersProps {
  selectedRoles: UserRole[];
  onRolesChange: (roles: UserRole[]) => void;
  selectedGroups: number[];
  onGroupsChange: (groupIds: number[]) => void;
  groups: GroupOption[];
  selectedStatuses: StatusFilter;
  onStatusesChange: (statuses: StatusFilter) => void;
  roleCounts: Record<string, number>;
  statusCounts: StatusCountMap;
}

export default function UserFilters({
  selectedRoles,
  onRolesChange,
  selectedGroups,
  onGroupsChange,
  groups,
  selectedStatuses,
  onStatusesChange,
  roleCounts,
  statusCounts,
}: UserFiltersProps) {
  const hasRoleFilter = selectedRoles.length > 0;
  const hasGroupFilter = selectedGroups.length > 0;
  const hasStatusFilter = selectedStatuses.length > 0;
  const [groupSearch, setGroupSearch] = useState("");
  const [groupPopoverOpen, setGroupPopoverOpen] = useState(false);

  const toggleRole = (role: UserRole) => {
    if (selectedRoles.includes(role)) {
      onRolesChange(selectedRoles.filter((r) => r !== role));
    } else {
      onRolesChange([...selectedRoles, role]);
    }
  };

  const toggleGroup = (groupId: number) => {
    if (selectedGroups.includes(groupId)) {
      onGroupsChange(selectedGroups.filter((id) => id !== groupId));
    } else {
      onGroupsChange([...selectedGroups, groupId]);
    }
  };

  const toggleStatus = (status: UserStatus) => {
    if (selectedStatuses.includes(status)) {
      onStatusesChange(selectedStatuses.filter((s) => s !== status));
    } else {
      onStatusesChange([...selectedStatuses, status]);
    }
  };

  const roleLabel = hasRoleFilter
    ? FILTERABLE_ROLES.filter(([role]) => selectedRoles.includes(role))
        .map(([, label]) => label)
        .slice(0, 2)
        .join(", ") +
      (selectedRoles.length > 2 ? `, +${selectedRoles.length - 2}` : "")
    : "All Account Types";

  const groupLabel = hasGroupFilter
    ? groups
        .filter((g) => selectedGroups.includes(g.id))
        .map((g) => g.name)
        .slice(0, 2)
        .join(", ") +
      (selectedGroups.length > 2 ? `, +${selectedGroups.length - 2}` : "")
    : "All Groups";

  const statusLabel = hasStatusFilter
    ? FILTERABLE_STATUSES.filter(([status]) =>
        selectedStatuses.includes(status)
      )
        .map(([, label]) => label)
        .slice(0, 2)
        .join(", ") +
      (selectedStatuses.length > 2 ? `, +${selectedStatuses.length - 2}` : "")
    : "All Status";

  const filteredGroups = groupSearch
    ? groups.filter((g) =>
        g.name.toLowerCase().includes(groupSearch.toLowerCase())
      )
    : groups;

  return (
    <div className="flex gap-2">
      {/* Role filter */}
      <Popover>
        <Popover.Trigger asChild>
          <FilterButton
            aria-label="Filter by role"
            icon={SvgUsers}
            active={hasRoleFilter}
            onClear={() => onRolesChange([])}
          >
            {roleLabel}
          </FilterButton>
        </Popover.Trigger>
        <Popover.Content align="start">
          <div className="flex flex-col gap-1 p-1 min-w-[200px]">
            <LineItem
              icon={!hasRoleFilter ? SvgCheck : SvgUsers}
              selected={!hasRoleFilter}
              emphasized={!hasRoleFilter}
              onClick={() => onRolesChange([])}
            >
              All Account Types
            </LineItem>
            {FILTERABLE_ROLES.map(([role, label]) => {
              const isSelected = selectedRoles.includes(role);
              const roleIcon = ROLE_ICONS[role] ?? SvgUser;
              return (
                <LineItem
                  key={role}
                  icon={isSelected ? SvgCheck : roleIcon}
                  strokeIcon={isSelected || role !== UserRole.SLACK_USER}
                  selected={isSelected}
                  emphasized={isSelected}
                  onClick={() => toggleRole(role)}
                  rightChildren={<CountBadge count={roleCounts[role]} />}
                >
                  {label}
                </LineItem>
              );
            })}
          </div>
        </Popover.Content>
      </Popover>

      {/* Groups filter */}
      <Popover
        open={groupPopoverOpen}
        onOpenChange={(open) => {
          setGroupPopoverOpen(open);
          if (!open) setGroupSearch("");
        }}
      >
        <Popover.Trigger asChild>
          <FilterButton
            aria-label="Filter by group"
            icon={SvgUsers}
            active={hasGroupFilter}
            onClear={() => onGroupsChange([])}
          >
            {groupLabel}
          </FilterButton>
        </Popover.Trigger>
        <Popover.Content align="start">
          <div className="flex flex-col gap-1 p-1 min-w-[200px]">
            <InputTypeIn
              value={groupSearch}
              onChange={(e) => setGroupSearch(e.target.value)}
              placeholder="Search groups..."
              leftSearchIcon
              variant="internal"
            />
            <LineItem
              icon={!hasGroupFilter ? SvgCheck : SvgUsers}
              selected={!hasGroupFilter}
              emphasized={!hasGroupFilter}
              onClick={() => onGroupsChange([])}
            >
              All Groups
            </LineItem>
            <ShadowDiv className="flex flex-col gap-1 max-h-[240px]">
              {filteredGroups.map((group) => {
                const isSelected = selectedGroups.includes(group.id);
                return (
                  <LineItem
                    key={group.id}
                    icon={isSelected ? SvgCheck : SvgUsers}
                    selected={isSelected}
                    emphasized={isSelected}
                    onClick={() => toggleGroup(group.id)}
                    rightChildren={<CountBadge count={group.memberCount} />}
                  >
                    {group.name}
                  </LineItem>
                );
              })}
              {filteredGroups.length === 0 && (
                <Text as="span" secondaryBody text03 className="px-2 py-1.5">
                  No groups found
                </Text>
              )}
            </ShadowDiv>
          </div>
        </Popover.Content>
      </Popover>

      {/* Status filter */}
      <Popover>
        <Popover.Trigger asChild>
          <FilterButton
            aria-label="Filter by status"
            icon={SvgUsers}
            active={hasStatusFilter}
            onClear={() => onStatusesChange([])}
          >
            {statusLabel}
          </FilterButton>
        </Popover.Trigger>
        <Popover.Content align="start">
          <div className="flex flex-col gap-1 p-1 min-w-[200px]">
            <LineItem
              icon={!hasStatusFilter ? SvgCheck : SvgUser}
              selected={!hasStatusFilter}
              emphasized={!hasStatusFilter}
              onClick={() => onStatusesChange([])}
            >
              All Status
            </LineItem>
            {FILTERABLE_STATUSES.map(([status, label]) => {
              const isSelected = selectedStatuses.includes(status);
              const countKey = STATUS_COUNT_KEY[status];
              return (
                <LineItem
                  key={status}
                  icon={isSelected ? SvgCheck : SvgUser}
                  selected={isSelected}
                  emphasized={isSelected}
                  onClick={() => toggleStatus(status)}
                  rightChildren={<CountBadge count={statusCounts[countKey]} />}
                >
                  {label}
                </LineItem>
              );
            })}
          </div>
        </Popover.Content>
      </Popover>
    </div>
  );
}
