"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  type DropdownMenuItem,
  type DropdownMenuRow,
} from "@opal/components";
import {
  SvgMoreHorizontal,
  SvgUsers,
  SvgXCircle,
  SvgUserCheck,
  SvgUserPlus,
  SvgUserX,
  SvgKey,
  SvgUserManage,
} from "@opal/icons";
import Text from "@/refresh-components/texts/Text";
import { AccountType, UserStatus } from "@/lib/types";
import { toast } from "@opal/layouts";
import { approveRequest, setUserAdminAccess } from "./svc";
import { useCanManageGroups } from "@/lib/permissions/hooks";
import EditUserModal from "./EditUserModal";
import {
  CancelInviteModal,
  DeactivateUserModal,
  ActivateUserModal,
  DeleteUserModal,
  ResetPasswordModal,
} from "./UserActionModals";
import type { UserRow } from "./types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

enum Modal {
  DEACTIVATE = "deactivate",
  ACTIVATE = "activate",
  DELETE = "delete",
  CANCEL_INVITE = "cancelInvite",
  EDIT_GROUPS = "editGroups",
  RESET_PASSWORD = "resetPassword",
}

interface UserRowActionsProps {
  user: UserRow;
  onMutate: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function UserRowActions({
  user,
  onMutate,
}: UserRowActionsProps) {
  const t = useTranslations("admin.users");
  const [modal, setModal] = useState<Modal | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  // below Business the group editor is empty, so don't offer it
  const canManageGroups = useCanManageGroups();

  const openModal = (type: Modal) => setModal(type);

  const closeModal = () => setModal(null);

  const closeAndMutate = () => {
    setModal(null);
    onMutate();
  };

  // the only edition-independent way to promote/demote; group editing is EE-only
  const toggleAdminAccess = () => {
    void (async () => {
      try {
        await setUserAdminAccess(user.email, !user.is_admin);
        onMutate();
        toast.success(
          user.is_admin
            ? t("rowActions.toasts.adminAccessRemoved")
            : t("rowActions.toasts.adminAccessGranted")
        );
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : t("rowActions.toasts.error")
        );
      }
    })();
  };

  const editGroupsItem: DropdownMenuRow[] =
    user.id && canManageGroups
      ? [
          {
            kind: "action",
            id: "edit-groups",
            icon: SvgUsers,
            title: t("rowActions.editGroups.label"),
            onSelect: () => openModal(Modal.EDIT_GROUPS),
          },
        ]
      : [];
  const adminAccessItem: DropdownMenuRow[] =
    user.id && user.account_type === AccountType.STANDARD
      ? [
          {
            kind: "action",
            id: "admin-access",
            icon: SvgUserManage,
            title: user.is_admin
              ? t("rowActions.removeAdmin.label")
              : t("rowActions.makeAdmin.label"),
            onSelect: toggleAdminAccess,
          },
        ]
      : [];
  const resetPasswordItem: DropdownMenuRow = {
    kind: "action",
    id: "reset-password",
    icon: SvgKey,
    title: t("rowActions.resetPassword.label"),
    onSelect: () => openModal(Modal.RESET_PASSWORD),
  };

  // Status-aware action menus. A line sits between groups.
  const menuItems: DropdownMenuItem[] = (() => {
    // SCIM-managed users get limited actions: most changes would be
    // overwritten on the next IdP sync. Deactivate shows, so a SCIM admin
    // can see the action exists, but never fires.
    if (user.is_scim_synced) {
      return [
        {
          kind: "group",
          items: [
            ...editGroupsItem,
            {
              kind: "action",
              id: "deactivate",
              icon: SvgUserX,
              danger: true,
              disabled: true,
              title: t("rowActions.deactivate.label"),
              onSelect: () => {},
            },
          ],
        },
        {
          kind: "group",
          items: [
            {
              kind: "custom",
              id: "scim-notice",
              disabled: true,
              render: ({ props }) => (
                <div {...props}>
                  <Text as="p" secondaryBody text03 className="px-3 py-1">
                    {t("rowActions.scimNotice.description")}
                  </Text>
                </div>
              ),
            },
          ],
        },
      ];
    }

    switch (user.status) {
      case UserStatus.INVITED:
        return [
          {
            kind: "action",
            id: "cancel-invite",
            icon: SvgXCircle,
            danger: true,
            title: t("rowActions.cancelInvite.label"),
            onSelect: () => openModal(Modal.CANCEL_INVITE),
          },
        ];

      case UserStatus.REQUESTED:
        return [
          {
            kind: "action",
            id: "approve",
            icon: SvgUserCheck,
            title: t("rowActions.approve.label"),
            onSelect: () => {
              void (async () => {
                try {
                  await approveRequest(user.email);
                  onMutate();
                  toast.success(t("rowActions.toasts.requestApproved"));
                } catch (err) {
                  toast.error(
                    err instanceof Error
                      ? err.message
                      : t("rowActions.toasts.error")
                  );
                }
              })();
            },
          },
        ];

      case UserStatus.ACTIVE:
        return [
          {
            kind: "group",
            items: [...editGroupsItem, ...adminAccessItem, resetPasswordItem],
          },
          {
            kind: "group",
            items: [
              {
                kind: "action",
                id: "deactivate",
                icon: SvgUserX,
                danger: true,
                title: t("rowActions.deactivate.label"),
                onSelect: () => openModal(Modal.DEACTIVATE),
              },
            ],
          },
        ];

      case UserStatus.INACTIVE:
        return [
          {
            kind: "group",
            items: [...editGroupsItem, ...adminAccessItem, resetPasswordItem],
          },
          {
            kind: "group",
            items: [
              {
                kind: "action",
                id: "activate",
                icon: SvgUserPlus,
                title: t("rowActions.activate.label"),
                onSelect: () => openModal(Modal.ACTIVATE),
              },
            ],
          },
          {
            kind: "group",
            items: [
              {
                kind: "action",
                id: "delete",
                icon: SvgUserX,
                danger: true,
                title: t("rowActions.delete.label"),
                onSelect: () => openModal(Modal.DELETE),
              },
            ],
          },
        ];

      default: {
        const _exhaustive: never = user.status;
        return [];
      }
    }
  })();

  return (
    <>
      <Dropdown open={menuOpen} onOpenChange={setMenuOpen}>
        <Dropdown.Trigger asChild>
          <Button
            prominence="tertiary"
            icon={SvgMoreHorizontal}
            aria-label={t("rowActions.menuButton.ariaLabel")}
          />
        </Dropdown.Trigger>
        <Dropdown.Data
          label={t("rowActions.menuButton.ariaLabel")}
          items={menuItems}
        />
      </Dropdown>

      {modal === Modal.EDIT_GROUPS && user.id && (
        <EditUserModal
          user={user as UserRow & { id: string }}
          onClose={closeModal}
          onMutate={onMutate}
        />
      )}

      {modal === Modal.CANCEL_INVITE && (
        <CancelInviteModal
          email={user.email}
          onClose={closeModal}
          onMutate={onMutate}
        />
      )}

      {modal === Modal.DEACTIVATE && (
        <DeactivateUserModal
          email={user.email}
          onClose={closeModal}
          onMutate={onMutate}
        />
      )}

      {modal === Modal.ACTIVATE && (
        <ActivateUserModal
          email={user.email}
          onClose={closeModal}
          onMutate={onMutate}
        />
      )}

      {modal === Modal.DELETE && (
        <DeleteUserModal
          email={user.email}
          onClose={closeModal}
          onMutate={onMutate}
        />
      )}

      {modal === Modal.RESET_PASSWORD && (
        <ResetPasswordModal email={user.email} onClose={closeModal} />
      )}
    </>
  );
}
