import { type User } from "@/lib/types";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";
import useSWRMutation from "swr/mutation";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";

const DeleteUserButton = ({
  user,
  setPopup,
  mutate,
  className,
  children,
}: {
  user: User;
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
  className?: string;
  children?: React.ReactNode;
}) => {
  const { trigger, isMutating } = useSWRMutation(
    "/api/manage/admin/delete-user",
    userMutationFetcher,
    {
      onSuccess: () => {
        mutate();
        setPopup({
          message: "User deleted successfully!",
          type: "success",
        });
      },
      onError: (errorMsg) =>
        setPopup({
          message: `Unable to delete user - ${errorMsg.message}`,
          type: "error",
        }),
    }
  );

  const [showDeleteModal, setShowDeleteModal] = useState(false);
  return (
    <>
      {showDeleteModal && (
        <ConfirmEntityModal
          entityType="user"
          entityName={user.email}
          onClose={() => setShowDeleteModal(false)}
          onSubmit={() => trigger({ user_email: user.email, method: "DELETE" })}
          additionalDetails="All data associated with this user will be deleted (including personas, tools and chat sessions)."
        />
      )}

      <Button
        className={className}
        onClick={() => setShowDeleteModal(true)}
        disabled={isMutating}
        size="sm"
        variant="destructive"
      >
        {children}
      </Button>
    </>
  );
};

export default DeleteUserButton;
