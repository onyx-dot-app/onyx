import {
  type InvitedUserSnapshot,
  type AcceptedUserSnapshot,
} from "@/lib/types";

import { toast } from "@/hooks/useToast";
import useSWRMutation from "swr/mutation";
import Button from "@/refresh-components/buttons/Button";
import GenericConfirmModal from "@/components/modals/GenericConfirmModal";
import { useState } from "react";

export const InviteUserButton = ({
  user,
  invited,
  mutate,
}: {
  user: AcceptedUserSnapshot | InvitedUserSnapshot;
  invited: boolean;
  mutate: (() => void) | (() => void)[];
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
        if (typeof mutate === "function") {
          mutate();
        } else {
          mutate.forEach((fn) => fn());
        }
        toast.success("User invited successfully!");
      },
      onError: (errorMsg) => {
        setShowInviteModal(false);
        toast.error(`Unable to invite user - ${errorMsg}`);
      },
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
        if (typeof mutate === "function") {
          mutate();
        } else {
          mutate.forEach((fn) => fn());
        }
        toast.success("User uninvited successfully!");
      },
      onError: (errorMsg) => {
        setShowInviteModal(false);
        toast.error(`Unable to uninvite user - ${errorMsg}`);
      },
    }
  );

  const [showInviteModal, setShowInviteModal] = useState(false);

  const handleConfirm = () => {
    const normalizedEmail = user.email.toLowerCase();
    if (invited) {
      uninviteTrigger({ user_email: normalizedEmail });
    } else {
      inviteTrigger({ emails: [normalizedEmail] });
    }
  };

  const isMutating = isInviting || isUninviting;

  return (
    <>
      {showInviteModal && (
        <GenericConfirmModal
          title={`${invited ? "Uninvite" : "Invite"} User`}
          message={`Are you sure you want to ${
            invited ? "uninvite" : "invite"
          } ${user.email}?`}
          onClose={() => setShowInviteModal(false)}
          onConfirm={handleConfirm}
        />
      )}

      <Button onClick={() => setShowInviteModal(true)} disabled={isMutating}>
        {invited ? "Uninvite" : "Invite"}
      </Button>
    </>
  );
};
