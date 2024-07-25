import { PopupSpec } from "@/components/admin/connectors/Popup";
import { CreateRateLimitModal } from "../../../../admin/token-rate-limits/CreateRateLimitModal";
import { Scope } from "../../../../admin/token-rate-limits/types";
import { insertGroupTokenRateLimit } from "../../../../admin/token-rate-limits/lib";
import { mutate } from "swr";

interface AddMemberFormProps {
  isOpen: boolean;
  setIsOpen: (isOpen: boolean) => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  userGroupId: number;
}

const handleCreateGroupTokenRateLimit = async (
  period_hours: number,
  token_budget: number,
  group_id: number = -1
) => {
  const tokenRateLimitArgs = {
    enabled: true,
    token_budget: token_budget,
    period_hours: period_hours,
  };
  return await insertGroupTokenRateLimit(tokenRateLimitArgs, group_id);
};

export const AddTokenRateLimitForm: React.FC<AddMemberFormProps> = ({
  isOpen,
  setIsOpen,
  setPopup,
  userGroupId,
}) => {
  const handleSubmit = (
    _: Scope,
    period_hours: number,
    token_budget: number,
    group_id: number = -1
  ) => {
    handleCreateGroupTokenRateLimit(period_hours, token_budget, group_id)
      .then(() => {
        setIsOpen(false);
        setPopup({ type: "success", message: "Token rate limit created!" });
        mutate(`/api/admin/token-rate-limits/user-group/${userGroupId}`);
      })
      .catch((error) => {
        setPopup({ type: "error", message: error.message });
      });
  };

  return (
    <CreateRateLimitModal
      isOpen={isOpen}
      setIsOpen={setIsOpen}
      onSubmit={handleSubmit}
      setPopup={setPopup}
      forSpecificScope={Scope.USER_GROUP}
      forSpecificUserGroup={userGroupId}
    />
  );
};
