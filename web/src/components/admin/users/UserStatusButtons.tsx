import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";
import {
  type User,
  UserRole,
  USER_ROLE_LABELS,
  INVALID_ROLE_HOVER_TEXT,
} from "@/lib/types";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";
import useSWRMutation from "swr/mutation";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { GenericConfirmModal } from "@/components/modals/GenericConfirmModal";
import { useState } from "react";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";

export const InviteUserButton = ({
  user,
  invited,
  setPopup,
  mutate,
}: {
  user: User;
  invited: boolean;
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
}) => {
  const { trigger: inviteTrigger, isMutating: isInviting } = useSWRMutation(
    "/api/manage/admin/users",
    async (url, { arg }: { arg: { emails: string[] } }) => {
      const response = await fetch(url, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(arg),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      return response.json();
    },
    {
      onSuccess: () => {
        setShowInviteModal(false);
        mutate();
        setPopup({
          message: "Пользователь успешно приглашен!",
          type: "success",
        });
      },
      onError: (errorMsg) =>
        setPopup({
          message: `Не удалось пригласить пользователя - ${errorMsg}`,
          type: "error",
        }),
    }
  );

  const { trigger: uninviteTrigger, isMutating: isUninviting } = useSWRMutation(
    "/api/manage/admin/remove-invited-user",
    async (url, { arg }: { arg: { user_email: string } }) => {
      const response = await fetch(url, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(arg),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      return response.json();
    },
    {
      onSuccess: () => {
        setShowInviteModal(false);
        mutate();
        setPopup({
          message: "Пользователь успешно отменил приглашение!",
          type: "success",
        });
      },
      onError: (errorMsg) =>
        setPopup({
          message: `Не удалось отменить приглашение пользователя - ${errorMsg}`,
          type: "error",
        }),
    }
  );

  const [showInviteModal, setShowInviteModal] = useState(false);

  const handleConfirm = () => {
    if (invited) {
      uninviteTrigger({ user_email: user.email });
    } else {
      inviteTrigger({ emails: [user.email] });
    }
  };

  const isMutating = isInviting || isUninviting;

  return (
    <>
      {showInviteModal && (
        <GenericConfirmModal
          title={`${invited ? i18n.t(k.UNINVITE) : i18n.t(k.INVITE)} ${i18n.t(
            k.USER
          )}`}
          message={`${i18n.t(k.ARE_YOU_SURE_YOU_WANT_TO)} ${
            invited ? i18n.t(k.UNINVITE1) : i18n.t(k.INVITE1)
          } ${user.email}${i18n.t(k._10)}`}
          onClose={() => setShowInviteModal(false)}
          onConfirm={handleConfirm}
        />
      )}

      <Button
        className="w-min"
        onClick={() => setShowInviteModal(true)}
        disabled={isMutating}
        size="sm"
      >
        {invited ? i18n.t(k.UNINVITE) : i18n.t(k.INVITE)}
      </Button>
    </>
  );
};

export const UserRoleDropdown = ({
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
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.entries(USER_ROLE_LABELS) as [UserRole, string][]).map(
            ([role, label]) => {
              // Dont want to ever show external permissioned users because it's scary
              if (role === UserRole.EXT_PERM_USER) return null;

              // Only want to show limited users if paid enterprise features are enabled
              // Also, dont want to show these other roles in general
              const isNotVisibleRole =
                (!isPaidEnterpriseFeaturesEnabled &&
                  role === UserRole.GLOBAL_CURATOR) ||
                role === UserRole.CURATOR ||
                role === UserRole.LIMITED;

              // Always show the current role
              const isCurrentRole = user.role === role;

              return isNotVisibleRole && !isCurrentRole ? null : (
                <SelectItem
                  key={role}
                  value={role}
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
          title="Изменить роль куратора"
          message={`${i18n.t(k.WARNING_SWITCHING_ROLES_FROM)} ${
            USER_ROLE_LABELS[pendingRole as UserRole] ??
            USER_ROLE_LABELS[user.role]
          } ${i18n.t(k.WILL_REMOVE_THEIR_STATUS_AS_IN)}`}
          confirmText={`${i18n.t(k.SWITCH_ROLE_TO)} ${
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
