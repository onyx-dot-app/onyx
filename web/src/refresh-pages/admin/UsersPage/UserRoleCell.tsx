"use client";

import { useState, useRef } from "react";
import { UserRole, USER_ROLE_LABELS } from "@/lib/types";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { OpenButton } from "@opal/components";
import { Disabled } from "@opal/core";
import {
  SvgCheck,
  SvgGlobe,
  SvgUser,
  SvgSlack,
  SvgUserManage,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
// TODO(@raunakab): migrate this `refresh-components/Text` to `@opal/components` Text
import Text from "@/refresh-components/texts/Text";
import Popover from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import { toast } from "@/hooks/useToast";
import { setUserRole } from "./svc";
import type { UserRow } from "./interfaces";

const ROLE_ICONS: Partial<Record<UserRole, IconFunctionComponent>> = {
  [UserRole.ADMIN]: SvgUserManage,
  [UserRole.GLOBAL_CURATOR]: SvgGlobe,
  [UserRole.SLACK_USER]: SvgSlack,
};

const SELECTABLE_ROLES = [
  UserRole.ADMIN,
  UserRole.GLOBAL_CURATOR,
  UserRole.BASIC,
] as const;

interface UserRoleCellProps {
  user: UserRow;
  onMutate: () => void;
}

export default function UserRoleCell({ user, onMutate }: UserRoleCellProps) {
  const [isUpdating, setIsUpdating] = useState(false);
  const [open, setOpen] = useState(false);
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const isUpdatingRef = useRef(false);

  if (!user.role) {
    return (
      <Text as="span" secondaryBody text03>
        —
      </Text>
    );
  }

  const applyRole = async (newRole: UserRole) => {
    if (isUpdatingRef.current) return;
    isUpdatingRef.current = true;
    setIsUpdating(true);
    try {
      await setUserRole(user.email, newRole);
      toast.success("Role updated");
      onMutate();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update role");
      onMutate();
    } finally {
      setIsUpdating(false);
      isUpdatingRef.current = false;
    }
  };

  const handleSelect = (role: UserRole) => {
    if (role === user.role) {
      setOpen(false);
      return;
    }
    setOpen(false);
    void applyRole(role);
  };

  const currentIcon = ROLE_ICONS[user.role] ?? SvgUser;

  const visibleRoles = isPaidEnterpriseFeaturesEnabled
    ? SELECTABLE_ROLES
    : SELECTABLE_ROLES.filter((r) => r !== UserRole.GLOBAL_CURATOR);

  const roleItems = visibleRoles.map((role) => {
    const isSelected = user.role === role;
    const icon = ROLE_ICONS[role] ?? SvgUser;
    return (
      <LineItem
        key={role}
        icon={isSelected ? SvgCheck : icon}
        selected={isSelected}
        emphasized={isSelected}
        onClick={() => handleSelect(role)}
      >
        {USER_ROLE_LABELS[role]}
      </LineItem>
    );
  });

  return (
    <Disabled disabled={isUpdating}>
      <Popover open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <OpenButton
            icon={currentIcon}
            variant="select-tinted"
            width="full"
            justifyContent="between"
            roundingVariant="compact"
          >
            {USER_ROLE_LABELS[user.role]}
          </OpenButton>
        </Popover.Trigger>
        <Popover.Content align="start">
          <div className="flex flex-col gap-1 p-1 min-w-[160px]">
            {roleItems}
          </div>
        </Popover.Content>
      </Popover>
    </Disabled>
  );
}
