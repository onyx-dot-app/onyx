"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import { SvgMoreHorizontal, SvgXCircle, SvgTrash, SvgCheck } from "@opal/icons";
import { Disabled } from "@opal/core";
import Popover from "@/refresh-components/Popover";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Text from "@/refresh-components/texts/Text";
import { UserStatus } from "@/lib/types";
import { toast } from "@/hooks/useToast";
import { deactivateUser, activateUser, deleteUser } from "./svc";
import type { UserRow } from "./interfaces";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ModalType = "deactivate" | "activate" | "delete" | null;

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

  // Only show actions for accepted users (active or inactive).
  // Invited/requested users have no row actions in this PR.
  if (
    user.status !== UserStatus.ACTIVE &&
    user.status !== UserStatus.INACTIVE
  ) {
    return null;
  }

  return (
    <>
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <Popover.Trigger asChild>
          <Button prominence="tertiary" icon={SvgMoreHorizontal} />
        </Popover.Trigger>
        <Popover.Content align="end">
          <div className="flex flex-col gap-0.5 p-1">
            {user.status === UserStatus.ACTIVE ? (
              <Button
                prominence="tertiary"
                icon={SvgXCircle}
                onClick={() => {
                  setPopoverOpen(false);
                  setModal("deactivate");
                }}
              >
                Deactivate User
              </Button>
            ) : (
              <>
                <Button
                  prominence="tertiary"
                  icon={SvgCheck}
                  onClick={() => {
                    setPopoverOpen(false);
                    setModal("activate");
                  }}
                >
                  Activate User
                </Button>
                <Button
                  prominence="tertiary"
                  variant="danger"
                  icon={SvgTrash}
                  onClick={() => {
                    setPopoverOpen(false);
                    setModal("delete");
                  }}
                >
                  Delete User
                </Button>
              </>
            )}
          </div>
        </Popover.Content>
      </Popover>

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
            be preserved. You can reactivate this account later.
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
            will be deleted. This cannot be undone.
          </Text>
        </ConfirmationModalLayout>
      )}
    </>
  );
}
