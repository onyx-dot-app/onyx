"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import {
  SvgMoreHorizontal,
  SvgUsers,
  SvgXCircle,
  SvgTrash,
  SvgCheck,
} from "@opal/icons";
import { Disabled } from "@opal/core";
import Popover from "@/refresh-components/Popover";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Text from "@/refresh-components/texts/Text";
import { UserStatus } from "@/lib/types";
import { toast } from "@/hooks/useToast";
import {
  deactivateUser,
  activateUser,
  deleteUser,
  cancelInvite,
  approveRequest,
} from "./svc";
import EditGroupsModal from "./EditGroupsModal";
import type { UserRow } from "./interfaces";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ModalType =
  | "deactivate"
  | "activate"
  | "delete"
  | "cancelInvite"
  | "editGroups"
  | null;

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
  const [modal, setModal] = useState<ModalType>(null);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleAction(
    action: () => Promise<void>,
    successMessage: string
  ) {
    setIsSubmitting(true);
    try {
      await action();
      onMutate();
      toast.success(successMessage);
      setModal(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsSubmitting(false);
    }
  }

  const openModal = (type: ModalType) => {
    setPopoverOpen(false);
    setModal(type);
  };

  // Status-aware action menus
  const actionButtons = (() => {
    switch (user.status) {
      case UserStatus.INVITED:
        return (
          <Button
            prominence="tertiary"
            variant="danger"
            icon={SvgXCircle}
            onClick={() => openModal("cancelInvite")}
          >
            Cancel Invite
          </Button>
        );

      case UserStatus.REQUESTED:
        return (
          <>
            <Button
              prominence="tertiary"
              icon={SvgCheck}
              onClick={() => {
                setPopoverOpen(false);
                handleAction(
                  () => approveRequest(user.email),
                  "Request approved"
                );
              }}
            >
              Approve
            </Button>
            <Button
              prominence="tertiary"
              variant="danger"
              icon={SvgXCircle}
              onClick={() => openModal("cancelInvite")}
            >
              Reject
            </Button>
          </>
        );

      case UserStatus.ACTIVE:
        return (
          <>
            {user.id && (
              <Button
                prominence="tertiary"
                icon={SvgUsers}
                onClick={() => openModal("editGroups")}
              >
                Groups
              </Button>
            )}
            <Button
              prominence="tertiary"
              icon={SvgXCircle}
              onClick={() => openModal("deactivate")}
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
                onClick={() => openModal("editGroups")}
              >
                Groups
              </Button>
            )}
            <Button
              prominence="tertiary"
              icon={SvgCheck}
              onClick={() => openModal("activate")}
            >
              Activate User
            </Button>
            <Button
              prominence="tertiary"
              variant="danger"
              icon={SvgTrash}
              onClick={() => openModal("delete")}
            >
              Delete User
            </Button>
          </>
        );
    }
  })();

  // SCIM-managed users cannot be modified from the UI — changes would be
  // overwritten on the next IdP sync.
  if (user.is_scim_synced) {
    return null;
  }

  return (
    <>
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <Popover.Trigger asChild>
          <Button prominence="tertiary" icon={SvgMoreHorizontal} />
        </Popover.Trigger>
        <Popover.Content align="end">
          <div className="flex flex-col gap-0.5 p-1">{actionButtons}</div>
        </Popover.Content>
      </Popover>

      {modal === "editGroups" && user.id && (
        <EditGroupsModal
          user={user as UserRow & { id: string }}
          onClose={() => setModal(null)}
          onMutate={onMutate}
        />
      )}

      {modal === "cancelInvite" && (
        <ConfirmationModalLayout
          icon={SvgXCircle}
          title={
            user.status === UserStatus.REQUESTED
              ? "Reject Request"
              : "Cancel Invite"
          }
          onClose={() => setModal(null)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                variant="danger"
                onClick={() => {
                  handleAction(
                    () => cancelInvite(user.email),
                    user.status === UserStatus.REQUESTED
                      ? "Request rejected"
                      : "Invite cancelled"
                  );
                }}
              >
                {user.status === UserStatus.REQUESTED ? "Reject" : "Cancel"}
              </Button>
            </Disabled>
          }
        >
          <Text as="p" text03>
            <Text as="span" text05>
              {user.email}
            </Text>{" "}
            {user.status === UserStatus.REQUESTED
              ? "will be removed from the pending requests list."
              : "will no longer be able to join Onyx with this invite."}
          </Text>
        </ConfirmationModalLayout>
      )}

      {modal === "deactivate" && (
        <ConfirmationModalLayout
          icon={SvgXCircle}
          title="Deactivate User"
          onClose={isSubmitting ? undefined : () => setModal(null)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                variant="danger"
                onClick={async () => {
                  await handleAction(
                    () => deactivateUser(user.email),
                    "User deactivated"
                  );
                }}
              >
                Deactivate
              </Button>
            </Disabled>
          }
        >
          <Text as="p" text03>
            <Text as="span" text05>
              {user.email}
            </Text>{" "}
            will immediately lose access to Onyx. Their sessions and agents will
            be preserved. Their license seat will be freed. You can reactivate
            this account later.
          </Text>
        </ConfirmationModalLayout>
      )}

      {modal === "activate" && (
        <ConfirmationModalLayout
          icon={SvgCheck}
          title="Activate User"
          onClose={isSubmitting ? undefined : () => setModal(null)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                onClick={async () => {
                  await handleAction(
                    () => activateUser(user.email),
                    "User activated"
                  );
                }}
              >
                Activate
              </Button>
            </Disabled>
          }
        >
          <Text as="p" text03>
            <Text as="span" text05>
              {user.email}
            </Text>{" "}
            will regain access to Onyx.
          </Text>
        </ConfirmationModalLayout>
      )}

      {modal === "delete" && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete User"
          onClose={isSubmitting ? undefined : () => setModal(null)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                variant="danger"
                onClick={async () => {
                  await handleAction(
                    () => deleteUser(user.email),
                    "User deleted"
                  );
                }}
              >
                Delete
              </Button>
            </Disabled>
          }
        >
          <Text as="p" text03>
            <Text as="span" text05>
              {user.email}
            </Text>{" "}
            will be permanently removed from Onyx. All of their session history
            will be deleted. Deletion cannot be undone.
          </Text>
        </ConfirmationModalLayout>
      )}
    </>
  );
}
