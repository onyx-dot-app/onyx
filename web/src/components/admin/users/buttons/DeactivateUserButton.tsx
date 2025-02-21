import { type User } from "@/lib/types";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { Button } from "@/components/ui/button";
import useSWRMutation from "swr/mutation";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";

const DeactivateUserButton = ({
  user,
  deactivate,
  setPopup,
  mutate,
  className,
  children,
}: {
  user: User;
  deactivate: boolean;
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
  className?: string;
  children?: React.ReactNode;
}) => {
  const { trigger, isMutating } = useSWRMutation(
    deactivate
      ? "/api/manage/admin/deactivate-user"
      : "/api/manage/admin/activate-user",
    userMutationFetcher,
    {
      onSuccess: () => {
        mutate();
        setPopup({
          message: `User ${deactivate ? "deactivated" : "activated"}!`,
          type: "success",
        });
      },
      onError: (errorMsg) =>
        setPopup({ message: errorMsg.message, type: "error" }),
    }
  );
  return (
    <Button
      className={className}
      onClick={() => trigger({ user_email: user.email })}
      disabled={isMutating}
      variant="ghost"
    >
      {children}
    </Button>
  );
};

export default DeactivateUserButton;
