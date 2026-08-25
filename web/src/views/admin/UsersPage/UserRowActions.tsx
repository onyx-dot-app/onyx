"use client";

import { useState } from "react";
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
          user.is_admin ? "Admin access removed" : "User is now an admin"
        );
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "An error occurred");
      }
    })();
  };

  const adminAccessItem = user.account_type === AccountType.STANDARD && (
    <LineItemButton
      sizePreset="main-ui"
      rounding="sm"
      icon={SvgUserManage}
      onClick={toggleAdminAccess}
      title={user.is_admin ? "Remove Admin Access" : "Make Admin"}
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
              rounding="sm"
              icon={SvgUsers}
              onClick={() => openModal(Modal.EDIT_GROUPS)}
              title="Groups & Roles"
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
                title="Deactivate User"
              />
            </div>
          </Disabled>
          <Divider paddingPerpendicular={4} />
          <Text as="p" secondaryBody text03 className="px-3 py-1">
            This is a synced SCIM user managed by your identity provider.
          </Text>
        </>
      );
    }

    switch (user.status) {
      case UserStatus.INVITED:
        return (
          <LineItemButton
            sizePreset="main-ui"
            rounding="sm"
            color="danger"
            icon={SvgXCircle}
            onClick={() => openModal(Modal.CANCEL_INVITE)}
            title="Cancel Invite"
          />
        );

      case UserStatus.REQUESTED:
        return (
          <LineItemButton
            sizePreset="main-ui"
            rounding="sm"
            icon={SvgUserCheck}
            onClick={() => {
              setPopoverOpen(false);
              void (async () => {
                try {
                  await approveRequest(user.email);
                  onMutate();
                  toast.success("Request approved");
                } catch (err) {
                  toast.error(
                    err instanceof Error ? err.message : "An error occurred"
                  );
                }
              })();
            }}
            title="Approve"
          />
        );

      case UserStatus.ACTIVE:
        return (
          <>
            {user.id && canManageGroups && (
              <LineItemButton
                sizePreset="main-ui"
                rounding="sm"
                icon={SvgUsers}
                onClick={() => openModal(Modal.EDIT_GROUPS)}
                title="Groups & Roles"
              />
            )}
            {user.id && adminAccessItem}
            <LineItemButton
              sizePreset="main-ui"
              rounding="sm"
              icon={SvgKey}
              onClick={() => openModal(Modal.RESET_PASSWORD)}
              title="Reset Password"
            />
            <Divider paddingPerpendicular={4} />
            <LineItemButton
              sizePreset="main-ui"
              rounding="sm"
              color="danger"
              icon={SvgUserX}
              onClick={() => openModal(Modal.DEACTIVATE)}
              title="Deactivate User"
            />
          </>
        );

      case UserStatus.INACTIVE:
        return (
          <>
            {user.id && canManageGroups && (
              <LineItemButton
                sizePreset="main-ui"
                rounding="sm"
                icon={SvgUsers}
                onClick={() => openModal(Modal.EDIT_GROUPS)}
                title="Groups & Roles"
              />
            )}
            {user.id && adminAccessItem}
            <LineItemButton
              sizePreset="main-ui"
              rounding="sm"
              icon={SvgKey}
              onClick={() => openModal(Modal.RESET_PASSWORD)}
              title="Reset Password"
            />
            <Divider paddingPerpendicular={4} />
            <LineItemButton
              sizePreset="main-ui"
              rounding="sm"
              icon={SvgUserPlus}
              onClick={() => openModal(Modal.ACTIVATE)}
              title="Activate User"
            />
            <Divider paddingPerpendicular={4} />
            <LineItemButton
              sizePreset="main-ui"
              rounding="sm"
              color="danger"
              icon={SvgUserX}
              onClick={() => openModal(Modal.DELETE)}
              title="Delete User"
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
