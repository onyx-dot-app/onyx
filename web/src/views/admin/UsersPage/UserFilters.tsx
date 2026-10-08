"use client";

import { useTranslations } from "next-intl";
import { SvgSlack, SvgUser, SvgGlobe, SvgKey, SvgUsers } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { Dropdown, FilterButton, type DropdownItem } from "@opal/components";
import { AccountType, UserStatus } from "@/lib/types";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import type { GroupOption, StatusFilter, StatusCountMap } from "./types";

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

  // Each list leads with an "All" row that reads as selected while nothing
  // is picked, and clears the filter when picked. The member counts ride as
  // the rows' suffixes.
  const ALL = "";
  const withAll = (title: string, rows: DropdownItem[]): DropdownItem[] => [
    { kind: "option", value: ALL, icon: SvgUsers, title, pinned: true },
    ...rows,
  ];
  const picked = (selected: string[]): ReadonlySet<string> =>
    new Set(selected.length > 0 ? selected : [ALL]);
  // A missing count reads as 0, so every row shows one.
  const count = (n: number | undefined) => String(n ?? 0);

  const accountTypeItems = withAll(
    t("filters.accountType.allOption.label"),
    FILTERABLE_ACCOUNT_TYPES.map((type) => ({
      kind: "option",
      value: type,
      icon: ACCOUNT_TYPE_ICONS[type] ?? SvgUser,
      title: accountTypeLabels[type],
      suffix: count(accountTypeCounts[type]),
    }))
  );
  const groupItems = withAll(
    t("filters.group.allOption.label"),
    groups.map((group) => ({
      kind: "option",
      value: String(group.id),
      icon: SvgUsers,
      title: group.name,
      suffix: count(group.memberCount),
    }))
  );
  const statusItems = withAll(
    t("filters.status.allOption.label"),
    FILTERABLE_STATUSES.map((status) => ({
      kind: "option",
      value: status,
      icon: SvgUser,
      title: statusLabels[status],
      suffix: count(statusCounts[STATUS_COUNT_KEY[status]]),
    }))
  );

  return (
    <div className="flex gap-2">
      {/* Account type filter */}
      <Dropdown>
        <Dropdown.Trigger asChild>
          <FilterButton
            aria-label={t("filters.accountType.button.ariaLabel")}
            icon={SvgUsers}
            active={hasTypeFilter}
            onClear={() => onAccountTypesChange([])}
          >
            {typeLabel}
          </FilterButton>
        </Dropdown.Trigger>
        <Dropdown.Data
          label={t("filters.accountType.button.ariaLabel")}
          values={picked(selectedAccountTypes)}
          onSelect={(option) => {
            if (option.value === ALL) onAccountTypesChange([]);
            else {
              const type = FILTERABLE_ACCOUNT_TYPES.find(
                (candidate) => candidate === option.value
              );
              if (type) toggleAccountType(type);
            }
          }}
          items={accountTypeItems}
        />
      </Dropdown>

      {/* Groups filter */}
      <Dropdown>
        <Dropdown.Trigger asChild>
          <FilterButton
            aria-label={t("filters.group.button.ariaLabel")}
            icon={SvgUsers}
            active={hasGroupFilter}
            onClear={() => onGroupsChange([])}
          >
            {groupLabel}
          </FilterButton>
        </Dropdown.Trigger>
        <Dropdown.Data
          label={t("filters.group.button.ariaLabel")}
          search={{ placeholder: t("filters.group.search.placeholder") }}
          noMatchText={t("filters.group.empty.label")}
          values={picked(selectedGroups.map(String))}
          onSelect={(option) => {
            if (option.value === ALL) onGroupsChange([]);
            else toggleGroup(Number(option.value));
          }}
          items={groupItems}
        />
      </Dropdown>

      {/* Status filter */}
      <Dropdown>
        <Dropdown.Trigger asChild>
          <FilterButton
            aria-label={t("filters.status.button.ariaLabel")}
            icon={SvgUsers}
            active={hasStatusFilter}
            onClear={() => onStatusesChange([])}
          >
            {statusLabel}
          </FilterButton>
        </Dropdown.Trigger>
        <Dropdown.Data
          label={t("filters.status.button.ariaLabel")}
          values={picked(selectedStatuses)}
          onSelect={(option) => {
            if (option.value === ALL) onStatusesChange([]);
            else {
              const status = FILTERABLE_STATUSES.find(
                (candidate) => candidate === option.value
              );
              if (status) toggleStatus(status);
            }
          }}
          items={statusItems}
        />
      </Dropdown>
    </div>
  );
}
