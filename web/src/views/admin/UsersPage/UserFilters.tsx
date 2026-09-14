"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  SvgCheck,
  SvgSlack,
  SvgUser,
  SvgGlobe,
  SvgKey,
  SvgUsers,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import {
  FilterButton,
  InputTypeIn,
  LineItemButton,
  Popover,
  ShadowDiv,
} from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { AccountType, UserStatus } from "@/lib/types";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import type { GroupOption, StatusFilter, StatusCountMap } from "./interfaces";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FILTERABLE_ACCOUNT_TYPES: AccountType[] = [
  AccountType.STANDARD,
  AccountType.BOT,
  AccountType.EXT_PERM_USER,
  AccountType.SERVICE_ACCOUNT,
];

const FILTERABLE_STATUSES: UserStatus[] = [
  UserStatus.ACTIVE,
  UserStatus.INACTIVE,
  UserStatus.INVITED,
  UserStatus.REQUESTED,
].filter(
  (value) => value !== UserStatus.REQUESTED || NEXT_PUBLIC_CLOUD_ENABLED
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
  const t = useTranslations("admin.users");
  const accountTypeLabels: Record<AccountType, string> = {
    [AccountType.STANDARD]: t("accountType.standard.label"),
    [AccountType.BOT]: t("accountType.bot.label"),
    [AccountType.EXT_PERM_USER]: t("accountType.extPermUser.label"),
    [AccountType.SERVICE_ACCOUNT]: t("accountType.serviceAccount.label"),
    [AccountType.ANONYMOUS]: t("accountType.anonymous.label"),
  };
  const statusLabels: Record<UserStatus, string> = {
    [UserStatus.ACTIVE]: t("status.active.label"),
    [UserStatus.INACTIVE]: t("status.inactive.label"),
    [UserStatus.INVITED]: t("status.invited.label"),
    [UserStatus.REQUESTED]: t("status.requested.label"),
  };

  // Names of the first two selections, plus a count of the rest.
  const summarize = (names: string[], selectedCount: number) => {
    const shown = names.slice(0, 2).join(", ");
    return selectedCount > 2
      ? t("filters.button.moreLabel", {
          names: shown,
          count: selectedCount - 2,
        })
      : shown;
  };

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
    ? summarize(
        FILTERABLE_ACCOUNT_TYPES.filter((type) =>
          selectedAccountTypes.includes(type)
        ).map((type) => accountTypeLabels[type]),
        selectedAccountTypes.length
      )
    : t("filters.accountType.allOption.label");

  const groupLabel = hasGroupFilter
    ? summarize(
        groups.filter((g) => selectedGroups.includes(g.id)).map((g) => g.name),
        selectedGroups.length
      )
    : t("filters.group.allOption.label");

  const statusLabel = hasStatusFilter
    ? summarize(
        FILTERABLE_STATUSES.filter((status) =>
          selectedStatuses.includes(status)
        ).map((status) => statusLabels[status]),
        selectedStatuses.length
      )
    : t("filters.status.allOption.label");

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
            aria-label={t("filters.accountType.button.ariaLabel")}
            icon={SvgUsers}
            active={hasTypeFilter}
            onClear={() => onAccountTypesChange([])}
          >
            {typeLabel}
          </FilterButton>
        </Popover.Trigger>
        <Popover.Content align="start">
          <div className="flex flex-col gap-1 p-1 min-w-[200px]">
            <LineItemButton
              sizePreset="main-ui"
              rounding={2}
              icon={!hasTypeFilter ? SvgCheck : SvgUsers}
              state={!hasTypeFilter ? "selected" : "empty"}
              selectVariant={!hasTypeFilter ? "select-heavy" : "select-light"}
              onClick={() => onAccountTypesChange([])}
              title={t("filters.accountType.allOption.label")}
            />
            {FILTERABLE_ACCOUNT_TYPES.map((type) => {
              const isSelected = selectedAccountTypes.includes(type);
              const typeIcon = ACCOUNT_TYPE_ICONS[type] ?? SvgUser;
              return (
                <LineItemButton
                  sizePreset="main-ui"
                  rounding={2}
                  key={type}
                  icon={isSelected ? SvgCheck : typeIcon}
                  state={isSelected ? "selected" : "empty"}
                  selectVariant={isSelected ? "select-heavy" : "select-light"}
                  onClick={() => toggleAccountType(type)}
                  rightChildren={<CountBadge count={accountTypeCounts[type]} />}
                  title={accountTypeLabels[type]}
                />
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
            aria-label={t("filters.group.button.ariaLabel")}
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
              placeholder={t("filters.group.search.placeholder")}
              searchIcon
              variant="internal"
            />
            <LineItemButton
              sizePreset="main-ui"
              rounding={2}
              icon={!hasGroupFilter ? SvgCheck : SvgUsers}
              state={!hasGroupFilter ? "selected" : "empty"}
              selectVariant={!hasGroupFilter ? "select-heavy" : "select-light"}
              onClick={() => onGroupsChange([])}
              title={t("filters.group.allOption.label")}
            />
            <ShadowDiv className="flex flex-col gap-1 max-h-[240px]">
              {filteredGroups.map((group) => {
                const isSelected = selectedGroups.includes(group.id);
                return (
                  <LineItemButton
                    sizePreset="main-ui"
                    rounding={2}
                    key={group.id}
                    icon={isSelected ? SvgCheck : SvgUsers}
                    state={isSelected ? "selected" : "empty"}
                    selectVariant={isSelected ? "select-heavy" : "select-light"}
                    onClick={() => toggleGroup(group.id)}
                    rightChildren={<CountBadge count={group.memberCount} />}
                    title={group.name}
                  />
                );
              })}
              {filteredGroups.length === 0 && (
                <Text as="span" secondaryBody text03 className="px-2 py-1.5">
                  {t("filters.group.empty.label")}
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
            aria-label={t("filters.status.button.ariaLabel")}
            icon={SvgUsers}
            active={hasStatusFilter}
            onClear={() => onStatusesChange([])}
          >
            {statusLabel}
          </FilterButton>
        </Popover.Trigger>
        <Popover.Content align="start">
          <div className="flex flex-col gap-1 p-1 min-w-[200px]">
            <LineItemButton
              sizePreset="main-ui"
              rounding={2}
              icon={!hasStatusFilter ? SvgCheck : SvgUser}
              state={!hasStatusFilter ? "selected" : "empty"}
              selectVariant={!hasStatusFilter ? "select-heavy" : "select-light"}
              onClick={() => onStatusesChange([])}
              title={t("filters.status.allOption.label")}
            />
            {FILTERABLE_STATUSES.map((status) => {
              const isSelected = selectedStatuses.includes(status);
              const countKey = STATUS_COUNT_KEY[status];
              return (
                <LineItemButton
                  sizePreset="main-ui"
                  rounding={2}
                  key={status}
                  icon={isSelected ? SvgCheck : SvgUser}
                  state={isSelected ? "selected" : "empty"}
                  selectVariant={isSelected ? "select-heavy" : "select-light"}
                  onClick={() => toggleStatus(status)}
                  rightChildren={<CountBadge count={statusCounts[countKey]} />}
                  title={statusLabels[status]}
                />
              );
            })}
          </div>
        </Popover.Content>
      </Popover>
    </div>
  );
}
