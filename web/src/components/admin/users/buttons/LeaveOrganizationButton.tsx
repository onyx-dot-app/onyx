import { type User } from "@/lib/types";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";
import useSWRMutation from "swr/mutation";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import { useRouter } from "next/navigation";

export const LeaveOrganizationButton = ({
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

  const [showLeaveModal, setShowLeaveModal] = useState(false);

  const handleLeaveOrganization = async () => {
    await trigger({ user_email: user.email, method: "POST" });
    router.push("/");
  };

  return (
    <>
      {showLeaveModal && (
        <ConfirmEntityModal
          actionButtonText="Leave"
          entityType="team"
          entityName="your team"
          onClose={() => setShowLeaveModal(false)}
          onSubmit={handleLeaveOrganization}
          additionalDetails="You will lose access to all team data and resources."
        />
      )}

      <Button
        className={className}
        onClick={() => setShowLeaveModal(true)}
        disabled={isMutating}
        variant="ghost"
      >
        {children}
      </Button>
    </>
  );
};
