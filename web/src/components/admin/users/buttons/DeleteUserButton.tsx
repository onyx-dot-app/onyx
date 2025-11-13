import { type User } from "@/lib/types";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";
import useSWRMutation from "swr/mutation";
import Button from "@/refresh-components/buttons/Button";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import { useModalProvider } from "@/refresh-components/contexts/ModalContext";

export interface DeleteUserButtonProps {
  user: User;
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
  className?: string;
  children?: React.ReactNode;
}

export default function DeleteUserButton({
  user,
  setPopup,
  mutate,
  className,
  children,
}: DeleteUserButtonProps) {
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

  const deleteModal = useModalProvider();
  return (
    <>
      <deleteModal.Provider>
        <ConfirmEntityModal
          entityType="user"
          entityName={user.email}
          onClose={() => deleteModal.toggle(false)}
          onSubmit={() => trigger({ user_email: user.email, method: "DELETE" })}
          additionalDetails="All data associated with this user will be deleted (including personas, tools and chat sessions)."
        />
      </deleteModal.Provider>

      <Button
        className={className}
        onClick={() => deleteModal.toggle(true)}
        disabled={isMutating}
        danger
      >
        {children}
      </Button>
    </>
  );
}
