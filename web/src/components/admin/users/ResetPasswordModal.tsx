import { useState } from "react";
import { Modal } from "@/components/Modal";
import Button from "@/refresh-components/buttons/Button";
import { User } from "@/lib/types";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgRefreshCw from "@/icons/refresh-cw";
import Text from "@/refresh-components/texts/Text";
import { LoadingAnimation } from "@/components/Loading";
import SvgCopy from "@/icons/copy";
import SvgCheck from "@/icons/check";

interface ResetPasswordModalProps {
  user: User;
  onClose: () => void;
  setPopup: (spec: PopupSpec) => void;
}

const ResetPasswordModal: React.FC<ResetPasswordModalProps> = ({
  user,
  onClose,
  setPopup,
}) => {
  const [newPassword, setNewPassword] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

  const handleResetPassword = async () => {
    setIsLoading(true);
    try {
      const response = await fetch("/api/password/reset_password", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ user_email: user.email }),
      });

      if (response.ok) {
        const data = await response.json();
        setNewPassword(data.new_password);
        setPopup({ message: "Password reset successfully", type: "success" });
      } else {
        const errorData = await response.json();
        setPopup({
          message: errorData.detail || "Failed to reset password",
          type: "error",
        });
      }
    } catch (error) {
      setPopup({
        message: "An error occurred while resetting the password",
        type: "error",
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopyPassword = () => {
    if (newPassword) {
      navigator.clipboard.writeText(newPassword);
      setPopup({ message: "Password copied to clipboard", type: "success" });
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000); // Reset after 2 seconds
    }
  };

  return (
    <Modal onOutsideClick={onClose} width="rounded-lg w-full max-w-md">
      <div className="p- text-neutral-900 dark:text-neutral-100">
        <h2 className="text-2xl font-bold mb-4">Reset Password</h2>
        <p className="mb-4">
          Are you sure you want to reset the password for {user.email}?
        </p>
        {newPassword ? (
          <div className="mb-4">
            <p className="font-semibold">New Password:</p>
            <div className="flex items-center bg-neutral-200 dark:bg-neutral-700 p-2 rounded">
              <p data-testid="new-password" className="flex-grow">
                {newPassword}
              </p>
              <IconButton
                secondary
                icon={isCopied ? SvgCheck : SvgCopy}
                onClick={handleCopyPassword}
              />
            </div>
            <Text text02>
              Please securely communicate this password to the user.
            </Text>
          </div>
        ) : (
          <Button
            onClick={handleResetPassword}
            disabled={isLoading}
            leftIcon={SvgRefreshCw}
          >
            {isLoading ? (
              <Text>
                <LoadingAnimation text="Resetting" />
              </Text>
            ) : (
              "Reset Password"
            )}
          </Button>
        )}
      </div>
    </Modal>
  );
};

export default ResetPasswordModal;
