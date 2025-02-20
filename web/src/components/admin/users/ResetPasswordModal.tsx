import { useState } from "react";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { User } from "@/lib/types";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { RefreshCcw, Copy, Check } from "lucide-react";

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
              <Button
                onClick={handleCopyPassword}
                variant="ghost"
                size="sm"
                className="ml-2"
              >
                {isCopied ? (
                  <Check className="w-4 h-4" />
                ) : (
                  <Copy className="w-4 h-4" />
                )}
              </Button>
            </div>
            <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-2">
              Please securely communicate this password to the user.
            </p>
          </div>
        ) : (
          <Button
            onClick={handleResetPassword}
            disabled={isLoading}
            className="w-full bg-neutral-700 hover:bg-neutral-600 dark:bg-neutral-200 dark:hover:bg-neutral-300 dark:text-neutral-900"
          >
            {isLoading ? (
              "Resetting..."
            ) : (
              <>
                <RefreshCcw className="w-4 h-4 mr-2" />
                Reset Password
              </>
            )}
          </Button>
        )}
      </div>
    </Modal>
  );
};

export default ResetPasswordModal;
