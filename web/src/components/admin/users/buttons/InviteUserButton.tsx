import {
  type InvitedUserSnapshot,
  type AcceptedUserSnapshot,
} from "@/lib/types";

import { PopupSpec } from "@/components/admin/connectors/Popup";
import useSWRMutation from "swr/mutation";
import { Button } from "@/components/ui/button";
import { GenericConfirmModal } from "@/components/modals/GenericConfirmModal";
import { useState } from "react";

export const InviteUserButton = ({
  user,
  invited,
  setPopup,
  mutate,
}: {
  user: AcceptedUserSnapshot | InvitedUserSnapshot;
  invited: boolean;
  setPopup: (spec: PopupSpec) => void;
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
        setPopup({
          message: "User invited successfully!",
          type: "success",
        });
      },
      onError: (errorMsg) => {
        setShowInviteModal(false);
        setPopup({
          message: `Unable to invite user - ${errorMsg}`,
          type: "error",
        });
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
        setPopup({
          message: "User uninvited successfully!",
          type: "success",
        });
      },
      onError: (errorMsg) => {
        setShowInviteModal(false);
        setPopup({
          message: `Unable to uninvite user - ${errorMsg}`,
          type: "error",
        });
      },
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
          title={`${invited ? "Uninvite" : "Invite"} User`}
          message={`Are you sure you want to ${
            invited ? "uninvite" : "invite"
          } ${user.email}?`}
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
        {invited ? "Uninvite" : "Invite"}
      </Button>
    </>
  );
};
