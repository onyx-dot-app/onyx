import { type User } from "@/lib/types";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import userMutationFetcher from "@/lib/admin/users/userMutationFetcher";
import useSWRMutation from "swr/mutation";
import { Button } from "@/components/ui/button";

export const DeactivaterButton = ({
  user,
  deactivate,
  setPopup,
  mutate,
}: {
  user: User;
  deactivate: boolean;
  setPopup: (spec: PopupSpec) => void;
  mutate: () => void;
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
      className="w-min"
      onClick={() => trigger({ user_email: user.email })}
      disabled={isMutating}
      size="sm"
    >
      {deactivate ? "Deactivate" : "Activate"}
    </Button>
  );
};
