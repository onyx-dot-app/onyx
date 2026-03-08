"use client";

import { SvgFilter, SvgUsers } from "@opal/icons";
import FilterButton from "@/refresh-components/buttons/FilterButton";
import Popover from "@/refresh-components/Popover";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import Text from "@/refresh-components/texts/Text";
import { UserRole, USER_ROLE_LABELS } from "@/lib/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UserFiltersProps {
  selectedRoles: UserRole[];
  onRolesChange: (roles: UserRole[]) => void;
  selectedStatus: "all" | "active" | "inactive";
  onStatusChange: (status: "all" | "active" | "inactive") => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FILTERABLE_ROLES = Object.entries(USER_ROLE_LABELS).filter(
  ([role]) => role !== UserRole.EXT_PERM_USER
) as [UserRole, string][];

const STATUS_OPTIONS = [
  { value: "all" as const, label: "All Status" },
  { value: "active" as const, label: "Active" },
  { value: "inactive" as const, label: "Inactive" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function UserFilters({
  selectedRoles,
  onRolesChange,
  selectedStatus,
  onStatusChange,
}: UserFiltersProps) {
  const hasRoleFilter = selectedRoles.length > 0;
  const hasStatusFilter = selectedStatus !== "all";

  const toggleRole = (role: UserRole) => {
    if (selectedRoles.includes(role)) {
      onRolesChange(selectedRoles.filter((r) => r !== role));
    } else {
      onRolesChange([...selectedRoles, role]);
    }
  };

  const roleLabel = hasRoleFilter
    ? `${selectedRoles.length} role${
        selectedRoles.length > 1 ? "s" : ""
      } selected`
    : "All Roles";

  const statusLabel = hasStatusFilter
    ? STATUS_OPTIONS.find((o) => o.value === selectedStatus)?.label ?? "Status"
    : "All Status";

  return (
    <div className="flex gap-2">
      {/* Role filter */}
      <Popover>
        <Popover.Trigger asChild>
          <FilterButton
            leftIcon={SvgUsers}
            active={hasRoleFilter}
            onClear={() => onRolesChange([])}
          >
            {roleLabel}
          </FilterButton>
        </Popover.Trigger>
        <Popover.Content align="start">
          <div className="flex flex-col gap-1 p-2 min-w-[200px]">
            {FILTERABLE_ROLES.map(([role, label]) => (
              <label
                key={role}
                className="flex items-center gap-2 px-2 py-1.5 rounded-8 cursor-pointer hover:bg-background-tint-01"
              >
                <Checkbox
                  checked={selectedRoles.includes(role)}
                  onCheckedChange={() => toggleRole(role)}
                />
                <Text as="span" mainUiAction>
                  {label}
                </Text>
              </label>
            ))}
          </div>
        </Popover.Content>
      </Popover>

      {/* Status filter */}
      <Popover>
        <Popover.Trigger asChild>
          <FilterButton
            leftIcon={SvgFilter}
            active={hasStatusFilter}
            onClear={() => onStatusChange("all")}
          >
            {statusLabel}
          </FilterButton>
        </Popover.Trigger>
        <Popover.Content align="start">
          <div className="flex flex-col gap-1 p-2 min-w-[160px]">
            {STATUS_OPTIONS.map((option) => (
              <label
                key={option.value}
                className="flex items-center gap-2 px-2 py-1.5 rounded-8 cursor-pointer hover:bg-background-tint-01"
              >
                <Checkbox
                  checked={selectedStatus === option.value}
                  onCheckedChange={() => onStatusChange(option.value)}
                />
                <Text as="span" mainUiAction>
                  {option.label}
                </Text>
              </label>
            ))}
          </div>
        </Popover.Content>
      </Popover>
    </div>
  );
}
