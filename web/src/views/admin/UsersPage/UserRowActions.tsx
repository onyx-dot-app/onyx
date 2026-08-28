"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Divider, LineItemButton, Popover } from "@opal/components";
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
import { Disabled } from "@opal/core";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { AccountType, UserStatus } from "@/lib/types";
import { ContentAction, toast } from "@opal/layouts";
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
import type { UserRow } from "./interfaces";

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
  const [popoverOpen, setPopoverOpen] = useState(false);
  // below Business the group editor is empty, so don't offer it
  const canManageGroups = useCanManageGroups();

  const openModal = (type: Modal) => {
    setPopoverOpen(false);
    setModal(type);
  };

  const closeModal = () => setModal(null);

  const closeAndMutate = () => {
    setModal(null);
    onMutate();
  };

  // the only edition-independent way to promote/demote; group editing is EE-only
  const toggleAdminAccess = () => {
    setPopoverOpen(false);
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

  const adminAccessItem = user.account_type === AccountType.STANDARD && (
    <LineItemButton
      sizePreset="main-ui"
      rounding={2}
      icon={SvgUserManage}
      onClick={toggleAdminAccess}
      title={
        user.is_admin
          ? t("rowActions.removeAdmin.label")
          : t("rowActions.makeAdmin.label")
      }
    />
  );

  // Status-aware action menus
  const actionButtons = (() => {
    // SCIM-managed users get limited actions — most changes would be
    // overwritten on the next IdP sync.
    if (user.is_scim_synced) {
      return (
        <>
          {user.id && canManageGroups && (
            <LineItemButton
              sizePreset="main-ui"
              rounding={2}
              icon={SvgUsers}
              onClick={() => openModal(Modal.EDIT_GROUPS)}
              title={t("rowActions.editGroups.label")}
            />
          )}
          {/* Shown so a SCIM admin can see the action exists, but it never
              fires — so it is a label, not a button. Padding matches
              LineItemButton so it lines up with the rows above. */}
          <Disabled disabled>
            <div className="w-full p-1.5">
              <ContentAction
                sizePreset="main-ui"
                padding={0.5}
                color="danger"
                icon={SvgUserX}
                title={t("rowActions.deactivate.label")}
              />
            </div>
          </Disabled>
          <Divider paddingPerpendicular={4} />
          <Text as="p" secondaryBody text03 className="px-3 py-1">
            {t("rowActions.scimNotice.description")}
          </Text>
        </>
      );
    }

    switch (user.status) {
      case UserStatus.INVITED:
        return (
          <LineItemButton
            sizePreset="main-ui"
            rounding={2}
            color="danger"
            icon={SvgXCircle}
            onClick={() => openModal(Modal.CANCEL_INVITE)}
            title={t("rowActions.cancelInvite.label")}
          />
        );

      case UserStatus.REQUESTED:
        return (
          <LineItemButton
            sizePreset="main-ui"
            rounding={2}
            icon={SvgUserCheck}
            onClick={() => {
              setPopoverOpen(false);
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
            }}
            title={t("rowActions.approve.label")}
          />
        );

      case UserStatus.ACTIVE:
        return (
          <>
            {user.id && canManageGroups && (
              <LineItemButton
                sizePreset="main-ui"
                rounding={2}
                icon={SvgUsers}
                onClick={() => openModal(Modal.EDIT_GROUPS)}
                title={t("rowActions.editGroups.label")}
              />
            )}
            {user.id && adminAccessItem}
            <LineItemButton
              sizePreset="main-ui"
              rounding={2}
              icon={SvgKey}
              onClick={() => openModal(Modal.RESET_PASSWORD)}
              title={t("rowActions.resetPassword.label")}
            />
            <Divider paddingPerpendicular={4} />
            <LineItemButton
              sizePreset="main-ui"
              rounding={2}
              color="danger"
              icon={SvgUserX}
              onClick={() => openModal(Modal.DEACTIVATE)}
              title={t("rowActions.deactivate.label")}
            />
          </>
        );

      case UserStatus.INACTIVE:
        return (
          <>
            {user.id && canManageGroups && (
              <LineItemButton
                sizePreset="main-ui"
                rounding={2}
                icon={SvgUsers}
                onClick={() => openModal(Modal.EDIT_GROUPS)}
                title={t("rowActions.editGroups.label")}
              />
            )}
            {user.id && adminAccessItem}
            <LineItemButton
              sizePreset="main-ui"
              rounding={2}
              icon={SvgKey}
              onClick={() => openModal(Modal.RESET_PASSWORD)}
              title={t("rowActions.resetPassword.label")}
            />
            <Divider paddingPerpendicular={4} />
            <LineItemButton
              sizePreset="main-ui"
              rounding={2}
              icon={SvgUserPlus}
              onClick={() => openModal(Modal.ACTIVATE)}
              title={t("rowActions.activate.label")}
            />
            <Divider paddingPerpendicular={4} />
            <LineItemButton
              sizePreset="main-ui"
              rounding={2}
              color="danger"
              icon={SvgUserX}
              onClick={() => openModal(Modal.DELETE)}
              title={t("rowActions.delete.label")}
            />
          </>
        );

      default: {
        const _exhaustive: never = user.status;
        return null;
      }
    }
  })();

  return (
    <>
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <Popover.Trigger asChild>
          <Button prominence="tertiary" icon={SvgMoreHorizontal} />
        </Popover.Trigger>
        <Popover.Content align="end" width="sm">
          <Section
            gap={2}
            height="auto"
            alignItems="stretch"
            justifyContent="start"
          >
            {actionButtons}
          </Section>
        </Popover.Content>
      </Popover>

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
