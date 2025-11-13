import { type User } from "@/lib/types";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";
import useSWRMutation from "swr/mutation";
import Button from "@/refresh-components/buttons/Button";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import { useRouter } from "next/navigation";
import { useModalProvider } from "@/refresh-components/contexts/ModalContext";

export interface LeaveOrganizationButtonProps {
  user: User;
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
  className?: string;
  children?: React.ReactNode;
}

export default function LeaveOrganizationButton({
  user,
  setPopup,
  mutate,
  className,
  children,
}: LeaveOrganizationButtonProps) {
  const router = useRouter();
  const { trigger, isMutating } = useSWRMutation(
    "/api/tenants/leave-team",
    userMutationFetcher,
    {
      onSuccess: () => {
        mutate();
        setPopup({
          message: "Successfully left the team!",
          type: "success",
        });
      },
      onError: (errorMsg) =>
        setPopup({
          message: `Unable to leave team - ${errorMsg}`,
          type: "error",
        }),
    }
  );

  const leaveModal = useModalProvider();

  const handleLeaveOrganization = async () => {
    await trigger({ user_email: user.email, method: "POST" });
    router.push("/");
  };

  return (
    <>
      <leaveModal.Provider>
        <ConfirmEntityModal
          actionButtonText="Leave"
          entityType="team"
          entityName="your team"
          onClose={() => leaveModal.toggle(false)}
          onSubmit={handleLeaveOrganization}
          additionalDetails="You will lose access to all team data and resources."
        />
      </leaveModal.Provider>

      <Button
        className={className}
        onClick={() => leaveModal.toggle(true)}
        disabled={isMutating}
        internal
      >
        {children}
      </Button>
    </>
  );
}
