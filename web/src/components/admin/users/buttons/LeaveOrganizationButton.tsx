import { type User } from "@/lib/types";
import { toast } from "@/hooks/useToast";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";
import useSWRMutation from "swr/mutation";
import Button from "@/refresh-components/buttons/Button";
import { useState } from "react";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import { useRouter } from "next/navigation";

export const LeaveOrganizationButton = ({
  user,
  mutate,
  className,
  children,
}: {
  user: User;
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
        toast.success("Successfully left the team!");
      },
      onError: (errorMsg) => toast.error(`Unable to leave team - ${errorMsg}`),
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
        internal
      >
        {children}
      </Button>
    </>
  );
};
