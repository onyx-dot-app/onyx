"use client";
import React from "react";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
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

export default function ResetPasswordModal({
  user,
  onClose,
  setPopup,
}: ResetPasswordModalProps) {
  const { t } = useTranslation();
  const [newPassword, setNewPassword] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isCopied, setIsCopied] = useState(false);

  const handleResetPassword = async () => {
    setIsLoading(true);
    try {
      const response = await fetch(
        `/api/manage/admin/users/${user.id}/reset-password`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
        }
      );

      if (response.ok) {
        const data = await response.json();
        setNewPassword(data.password);
        setPopup({
          message: t(k.PASSWORD_RESET_SUCCESSFULLY_R),
          type: "success",
        });
      } else {
        setPopup({
          message: t(k.FAILED_TO_CHANGE_PASSWORD),
          type: "error",
        });
      }
    } catch (error) {
      setPopup({
        message: t(k.FAILED_TO_CHANGE_PASSWORD),
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
      setTimeout(() => setIsCopied(false), 2000);
    }
  };

  return (
    <Modal onOutsideClick={onClose} width="rounded-lg w-full max-w-md">
      <div className="p-6 text-neutral-900 dark:text-neutral-100">
        <h2 className="text-2xl font-bold mb-4">{t(k.RESET_PASSWORD)}</h2>
        <p className="mb-4">
          {t(k.ARE_YOU_SURE_YOU_WANT_TO_RESET)} {user.email}
          {t(k._10)}
        </p>
        {newPassword ? (
          <div className="mb-4">
            <p className="font-semibold">{t(k.NEW_PASSWORD)}</p>
            <div className="flex items-center gap-2 mt-2">
              <div className="flex-1 p-2 bg-gray-100 dark:bg-gray-800 rounded border font-mono text-sm">
                {newPassword}
              </div>
              <Button
                onClick={handleCopyPassword}
                variant="outline"
                size="sm"
                className="flex items-center gap-2"
              >
                {isCopied ? (
                  <>
                    <Check className="w-4 h-4" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy className="w-4 h-4" />
                    Copy
                  </>
                )}
              </Button>
            </div>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
              {t(k.PLEASE_SECURELY_COMMUNICATE_TH)}
            </p>
          </div>
        ) : (
          <Button
            onClick={handleResetPassword}
            disabled={isLoading}
            className="w-full"
          >
            {isLoading ? (
              <>
                <RefreshCcw className="w-4 h-4 mr-2 animate-spin" />
                {t(k.RESETTING)}
              </>
            ) : (
              <>
                <RefreshCcw className="w-4 h-4 mr-2" />
                {t(k.RESET_PASSWORD)}
              </>
            )}
          </Button>
        )}
      </div>
    </Modal>
  );
}
