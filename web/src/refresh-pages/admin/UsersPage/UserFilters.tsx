"use client";

import { useState } from "react";
import {
  SvgCheck,
  SvgSlack,
  SvgUser,
  SvgGlobe,
  SvgKey,
  SvgUsers,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { FilterButton } from "@opal/components";
import { Popover } from "@opal/components";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import { ShadowDiv } from "@opal/components";
import {
  AccountType,
  ACCOUNT_TYPE_LABELS,
  UserStatus,
  USER_STATUS_LABELS,
} from "@/lib/types";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import type { GroupOption, StatusFilter, StatusCountMap } from "./interfaces";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FILTERABLE_ACCOUNT_TYPES: [AccountType, string][] = [
  [AccountType.STANDARD, ACCOUNT_TYPE_LABELS[AccountType.STANDARD]],
  [AccountType.BOT, ACCOUNT_TYPE_LABELS[AccountType.BOT]],
  [AccountType.EXT_PERM_USER, ACCOUNT_TYPE_LABELS[AccountType.EXT_PERM_USER]],
  [
    AccountType.SERVICE_ACCOUNT,
    ACCOUNT_TYPE_LABELS[AccountType.SERVICE_ACCOUNT],
  ],
];

const FILTERABLE_STATUSES = (
  Object.entries(USER_STATUS_LABELS) as [UserStatus, string][]
).filter(
  ([value]) => value !== UserStatus.REQUESTED || NEXT_PUBLIC_CLOUD_ENABLED
);

const ACCOUNT_TYPE_ICONS: Partial<Record<AccountType, IconFunctionComponent>> =
  {
    [AccountType.BOT]: SvgSlack,
    [AccountType.EXT_PERM_USER]: SvgGlobe,
    [AccountType.SERVICE_ACCOUNT]: SvgKey,
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
  selectedAccountTypes: AccountType[];
  onAccountTypesChange: (types: AccountType[]) => void;
  selectedGroups: number[];
  onGroupsChange: (groupIds: number[]) => void;
  groups: GroupOption[];
  selectedStatuses: StatusFilter;
  onStatusesChange: (statuses: StatusFilter) => void;
  accountTypeCounts: Record<string, number>;
  statusCounts: StatusCountMap;
}

export default function UserFilters({
  selectedAccountTypes,
  onAccountTypesChange,
  selectedGroups,
  onGroupsChange,
  groups,
  selectedStatuses,
  onStatusesChange,
  accountTypeCounts,
  statusCounts,
}: UserFiltersProps) {
  const hasTypeFilter = selectedAccountTypes.length > 0;
  const hasGroupFilter = selectedGroups.length > 0;
  const hasStatusFilter = selectedStatuses.length > 0;
  const [groupSearch, setGroupSearch] = useState("");
  const [groupPopoverOpen, setGroupPopoverOpen] = useState(false);

  const toggleAccountType = (type: AccountType) => {
    if (selectedAccountTypes.includes(type)) {
      onAccountTypesChange(selectedAccountTypes.filter((t) => t !== type));
    } else {
      onAccountTypesChange([...selectedAccountTypes, type]);
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

  const typeLabel = hasTypeFilter
    ? FILTERABLE_ACCOUNT_TYPES.filter(([type]) =>
        selectedAccountTypes.includes(type)
      )
        .map(([, label]) => label)
        .slice(0, 2)
        .join(", ") +
      (selectedAccountTypes.length > 2
        ? `, +${selectedAccountTypes.length - 2}`
        : "")
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
      {/* Account type filter */}
      <Popover>
        <Popover.Trigger asChild>
          <FilterButton
            aria-label="Filter by account type"
            icon={SvgUsers}
            active={hasTypeFilter}
            onClear={() => onAccountTypesChange([])}
          >
            {typeLabel}
          </FilterButton>
        </Popover.Trigger>
        <Popover.Content align="start">
          <div className="flex flex-col gap-1 p-1 min-w-[200px]">
            <LineItem
              icon={!hasTypeFilter ? SvgCheck : SvgUsers}
              selected={!hasTypeFilter}
              emphasized={!hasTypeFilter}
              onClick={() => onAccountTypesChange([])}
            >
              All Account Types
            </LineItem>
            {FILTERABLE_ACCOUNT_TYPES.map(([type, label]) => {
              const isSelected = selectedAccountTypes.includes(type);
              const typeIcon = ACCOUNT_TYPE_ICONS[type] ?? SvgUser;
              return (
                <LineItem
                  key={type}
                  icon={isSelected ? SvgCheck : typeIcon}
                  selected={isSelected}
                  emphasized={isSelected}
                  onClick={() => toggleAccountType(type)}
                  rightChildren={<CountBadge count={accountTypeCounts[type]} />}
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
