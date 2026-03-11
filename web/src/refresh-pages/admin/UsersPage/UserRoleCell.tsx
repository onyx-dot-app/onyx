"use client";

import { useState } from "react";
import { UserRole, USER_ROLE_LABELS } from "@/lib/types";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { OpenButton } from "@opal/components";
import GenericConfirmModal from "@/components/modals/GenericConfirmModal";
import {
  SvgCheck,
  SvgGlobe,
  SvgUser,
  SvgSlack,
  SvgUserManage,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import Popover from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import { setUserRole } from "./svc";
import type { UserRow } from "./interfaces";

const ROLE_ICONS: Record<string, IconFunctionComponent> = {
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
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [pendingRole, setPendingRole] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  if (!user.role) {
    return (
      <Text as="span" secondaryBody text03>
        —
      </Text>
    );
  }

  const applyRole = async (newRole: string) => {
    setIsUpdating(true);
    try {
      await setUserRole(user.email, newRole);
      onMutate();
    } catch {
      onMutate();
    } finally {
      setIsUpdating(false);
    }
  };

  const handleSelect = (role: UserRole) => {
    if (role === user.role) {
      setOpen(false);
      return;
    }
    setOpen(false);
    if (user.role === UserRole.CURATOR) {
      setPendingRole(role);
      setShowConfirmModal(true);
    } else {
      applyRole(role);
    }
  };

  const handleConfirm = () => {
    if (pendingRole) {
      applyRole(pendingRole);
    }
    setShowConfirmModal(false);
    setPendingRole(null);
  };

  const currentIcon = ROLE_ICONS[user.role] ?? SvgUser;

  return (
    <>
      {showConfirmModal && (
        <GenericConfirmModal
          title="Change Curator Role"
          message={`Warning: Switching roles from Curator to ${
            USER_ROLE_LABELS[pendingRole as UserRole] ??
            USER_ROLE_LABELS[user.role]
          } will remove their status as individual curators from all groups.`}
          confirmText={`Switch Role to ${
            USER_ROLE_LABELS[pendingRole as UserRole] ??
            USER_ROLE_LABELS[user.role]
          }`}
          onClose={() => setShowConfirmModal(false)}
          onConfirm={handleConfirm}
        />
      )}

      <Popover open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <OpenButton
            icon={currentIcon}
            variant="select-tinted"
            width="full"
            justifyContent="between"
            disabled={isUpdating}
          >
            {USER_ROLE_LABELS[user.role]}
          </OpenButton>
        </Popover.Trigger>
        <Popover.Content align="start">
          <div className="flex flex-col gap-1 p-1 min-w-[160px]">
            {SELECTABLE_ROLES.map((role) => {
              if (
                role === UserRole.GLOBAL_CURATOR &&
                !isPaidEnterpriseFeaturesEnabled
              ) {
                return null;
              }
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
            })}
          </div>
        </Popover.Content>
      </Popover>
    </>
  );
}
