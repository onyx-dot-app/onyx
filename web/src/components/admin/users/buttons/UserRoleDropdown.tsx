import {
  type User,
  UserRole,
  USER_ROLE_LABELS,
  INVALID_ROLE_HOVER_TEXT,
} from "@/lib/types";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";
import useSWRMutation from "swr/mutation";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { GenericConfirmModal } from "@/components/modals/GenericConfirmModal";
import { useState } from "react";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";

const UserRoleDropdown = ({
  user,
  onSuccess,
  onError,
}: {
  user: User;
  onSuccess: () => void;
  onError: (message: string) => void;
}) => {
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [pendingRole, setPendingRole] = useState<string | null>(null);

  const { trigger: setUserRole, isMutating: isSettingRole } = useSWRMutation(
    "/api/manage/set-user-role",
    userMutationFetcher,
    { onSuccess, onError }
  );
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  const handleChange = (value: string) => {
    if (value === user.role) return;
    if (user.role === UserRole.CURATOR) {
      setShowConfirmModal(true);
      setPendingRole(value);
    } else {
      setUserRole({
        user_email: user.email,
        new_role: value,
      });
    }
  };

  const handleConfirm = () => {
    if (pendingRole) {
      setUserRole({
        user_email: user.email,
        new_role: pendingRole,
      });
    }
    setShowConfirmModal(false);
    setPendingRole(null);
  };

  return (
    <>
      <Select
        value={user.role}
        onValueChange={handleChange}
        disabled={isSettingRole}
      >
        <SelectTrigger data-testid={`user-role-dropdown-trigger-${user.email}`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.entries(USER_ROLE_LABELS) as [UserRole, string][]).map(
            ([role, label]) => {
              // Don't want to ever show external permissioned users because it's scary
              if (role === UserRole.EXT_PERM_USER) return null;

              // Only want to show limited users if paid enterprise features are enabled
              // Also, dont want to show these other roles in general
              const isNotVisibleRole =
                (!isPaidEnterpriseFeaturesEnabled &&
                  role === UserRole.GLOBAL_CURATOR) ||
                role === UserRole.CURATOR ||
                role === UserRole.LIMITED ||
                role === UserRole.SLACK_USER;

              // Always show the current role
              const isCurrentRole = user.role === role;

              return isNotVisibleRole && !isCurrentRole ? null : (
                <SelectItem
                  key={role}
                  onClick={() => {
                    console.log("clicked");
                  }}
                  value={role}
                  data-testid={`user-role-dropdown-${role}`}
                  title={INVALID_ROLE_HOVER_TEXT[role] ?? ""}
                  data-tooltip-delay="0"
                >
                  {label}
                </SelectItem>
              );
            }
          )}
        </SelectContent>
      </Select>
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
    </>
  );
};

export default UserRoleDropdown;
