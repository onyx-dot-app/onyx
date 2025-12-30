import { useState } from "react";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import { User } from "@/lib/types";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import Text from "@/refresh-components/texts/Text";
import { LoadingAnimation } from "@/components/Loading";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import { SvgKey, SvgRefreshCw } from "@opal/icons";

export interface ResetPasswordModalProps {
  user: User;
  onClose: () => void;
  setPopup: (spec: PopupSpec) => void;
}

export default function ResetPasswordModal({
  user,
  onClose,
  setPopup,
}: ResetPasswordModalProps) {
  const [newPassword, setNewPassword] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

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

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content small>
        <Modal.Header
          icon={SvgKey}
          title="Reset Password"
          onClose={onClose}
          description={
            newPassword
              ? undefined
              : `Are you sure you want to reset the password for ${user.email}?`
          }
        />
        <Modal.Body>
          {newPassword ? (
            <div>
              <Text as="p">New Password:</Text>
              <div className="flex items-center bg-background-tint-03 p-2 rounded gap-2">
                <Text as="p" data-testid="new-password" className="flex-grow">
                  {newPassword}
                </Text>
                <CopyIconButton getCopyText={() => newPassword} />
              </div>
              <Text as="p" text02>
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
                <Text as="p">
                  <LoadingAnimation text="Resetting" />
                </Text>
              ) : (
                "Reset Password"
              )}
            </Button>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
