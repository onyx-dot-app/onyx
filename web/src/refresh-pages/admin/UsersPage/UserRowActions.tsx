"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import {
  SvgMoreHorizontal,
  SvgUsers,
  SvgXCircle,
  SvgUserCheck,
  SvgUserPlus,
  SvgUserX,
  SvgKey,
} from "@opal/icons";
import { Disabled } from "@opal/core";
import Popover from "@/refresh-components/Popover";
import Separator from "@/refresh-components/Separator";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { UserStatus } from "@/lib/types";
import { toast } from "@/hooks/useToast";
import { approveRequest } from "./svc";
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

  const openModal = (type: Modal) => {
    setPopoverOpen(false);
    setModal(type);
  };

  const closeModal = () => setModal(null);

  const closeAndMutate = () => {
    setModal(null);
    onMutate();
  };

  // Status-aware action menus
  const actionButtons = (() => {
    // SCIM-managed users get limited actions — most changes would be
    // overwritten on the next IdP sync.
    if (user.is_scim_synced) {
      return (
        <>
          {user.id && (
            <Button
              prominence="tertiary"
              icon={SvgUsers}
              onClick={() => openModal(Modal.EDIT_GROUPS)}
            >
              Groups &amp; Roles
            </Button>
          )}
          <Disabled disabled>
            <Button prominence="tertiary" variant="danger" icon={SvgUserX}>
              Deactivate User
            </Button>
          </Disabled>
          <Separator paddingXRem={0.5} />
          <Text as="p" secondaryBody text03 className="px-3 py-1">
            This is a synced SCIM user managed by your identity provider.
          </Text>
        </>
      );
    }

    switch (user.status) {
      case UserStatus.INVITED:
        return (
          <Button
            prominence="tertiary"
            variant="danger"
            icon={SvgXCircle}
            onClick={() => openModal(Modal.CANCEL_INVITE)}
          >
            Cancel Invite
          </Button>
        );

      case UserStatus.REQUESTED:
        return (
          <Button
            prominence="tertiary"
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
          >
            Approve
          </Button>
        );

      case UserStatus.ACTIVE:
        return (
          <>
            {user.id && (
              <Button
                prominence="tertiary"
                icon={SvgUsers}
                onClick={() => openModal(Modal.EDIT_GROUPS)}
              >
                Groups &amp; Roles
              </Button>
            )}
            <Button
              prominence="tertiary"
              icon={SvgKey}
              onClick={() => openModal(Modal.RESET_PASSWORD)}
            >
              Reset Password
            </Button>
            <Separator paddingXRem={0.5} />
            <Button
              prominence="tertiary"
              variant="danger"
              icon={SvgUserX}
              onClick={() => openModal(Modal.DEACTIVATE)}
            >
              Deactivate User
            </Button>
          </>
        );

      case UserStatus.INACTIVE:
        return (
          <>
            {user.id && (
              <Button
                prominence="tertiary"
                icon={SvgUsers}
                onClick={() => openModal(Modal.EDIT_GROUPS)}
              >
                Groups &amp; Roles
              </Button>
            )}
            <Button
              prominence="tertiary"
              icon={SvgKey}
              onClick={() => openModal(Modal.RESET_PASSWORD)}
            >
              Reset Password
            </Button>
            <Separator paddingXRem={0.5} />
            <Button
              prominence="tertiary"
              icon={SvgUserPlus}
              onClick={() => openModal(Modal.ACTIVATE)}
            >
              Activate User
            </Button>
            <Separator paddingXRem={0.5} />
            <Button
              prominence="tertiary"
              variant="danger"
              icon={SvgUserX}
              onClick={() => openModal(Modal.DELETE)}
            >
              Delete User
            </Button>
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
            gap={0.5}
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
