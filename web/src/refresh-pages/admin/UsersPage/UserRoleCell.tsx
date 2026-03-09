"use client";

import { useState } from "react";
import { UserRole, USER_ROLE_LABELS } from "@/lib/types";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import GenericConfirmModal from "@/components/modals/GenericConfirmModal";
import { setUserRole } from "./svc";
import type { UserRow } from "./interfaces";

interface UserRoleCellProps {
  user: UserRow;
  onMutate: () => void;
}

export default function UserRoleCell({ user, onMutate }: UserRoleCellProps) {
  const [isUpdating, setIsUpdating] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [pendingRole, setPendingRole] = useState<string | null>(null);
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  const applyRole = async (newRole: string) => {
    setIsUpdating(true);
    try {
      await setUserRole(user.email, newRole);
      onMutate();
    } catch {
      // error is surfaced by svc layer; refresh to show current state
      onMutate();
    } finally {
      setIsUpdating(false);
    }
  };

  const handleChange = (value: string) => {
    if (value === user.role) return;
    if (user.role === UserRole.CURATOR) {
      setPendingRole(value);
      setShowConfirmModal(true);
    } else {
      applyRole(value);
    }
  };

  const handleConfirm = () => {
    if (pendingRole) {
      applyRole(pendingRole);
    }
    setShowConfirmModal(false);
    setPendingRole(null);
  };

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

      <InputSelect
        value={user.role}
        onValueChange={handleChange}
        disabled={isUpdating}
      >
        <InputSelect.Trigger />

        <InputSelect.Content>
          {(Object.entries(USER_ROLE_LABELS) as [UserRole, string][]).map(
            ([role, label]) => {
              if (role === UserRole.EXT_PERM_USER) return null;

              const isNotVisibleRole =
                (!isPaidEnterpriseFeaturesEnabled &&
                  role === UserRole.GLOBAL_CURATOR) ||
                role === UserRole.CURATOR ||
                role === UserRole.LIMITED ||
                role === UserRole.SLACK_USER;

              const isCurrentRole = user.role === role;

              return isNotVisibleRole && !isCurrentRole ? null : (
                <InputSelect.Item key={role} value={role}>
                  {label}
                </InputSelect.Item>
              );
            }
          )}
        </InputSelect.Content>
      </InputSelect>
    </>
  );
}
