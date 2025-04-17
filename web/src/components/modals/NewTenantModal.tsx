"use client";
import i18n from "@/i18n/init";
import k from "./../../i18n/keys";

import { useState } from "react";
import { Dialog } from "@headlessui/react";
import { Button } from "../ui/button";
import { usePopup } from "@/components/admin/connectors/Popup";
import { ArrowRight, X } from "lucide-react";
import { logout } from "@/lib/user";
import { useUser } from "../user/UserProvider";
import { NewTenantInfo } from "@/lib/types";
import { useRouter } from "next/navigation";

// App domain should not be hardcoded
const APP_DOMAIN = process.env.NEXT_PUBLIC_APP_DOMAIN || "onyx.app";

interface NewTenantModalProps {
  tenantInfo: NewTenantInfo;
  isInvite?: boolean;
  onClose?: () => void;
}

export default function NewTenantModal({
  tenantInfo,
  isInvite = false,
  onClose,
}: NewTenantModalProps) {
  const router = useRouter();
  const { setPopup } = usePopup();
  const { user } = useUser();
  const [isOpen, setIsOpen] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClose = () => {
    setIsOpen(false);
    onClose?.();
  };

  const handleJoinTenant = async () => {
    setIsLoading(true);
    setError(null);

    try {
      if (isInvite) {
        // Accept the invitation through the API
        const response = await fetch("/api/tenants/users/invite/accept", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ tenant_id: tenantInfo.tenant_id }),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.message || "Failed to accept invitation");
        }

        setPopup({
          message: "You have accepted the invitation.",
          type: "success",
        });
      } else {
        // For non-invite flow, just show success message
        setPopup({
          message: "Processing your team join request...",
          type: "success",
        });
      }

      // Common logout and redirect for both flows
      await logout();
      router.push(`/auth/join?email=${encodeURIComponent(user?.email || "")}`);
      handleClose();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to join the team. Please try again.";

      setError(message);
      setPopup({
        message,
        type: "error",
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleRejectInvite = async () => {
    if (!isInvite) return;

    setIsLoading(true);
    setError(null);

    try {
      // Deny the invitation through the API
      const response = await fetch("/api/tenants/users/invite/deny", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tenant_id: tenantInfo.tenant_id }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || "Failed to decline invitation");
      }

      setPopup({
        message: "You have declined the invitation.",
        type: "info",
      });
      handleClose();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to decline the invitation. Please try again.";

      setError(message);
      setPopup({
        message,
        type: "error",
      });
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <Dialog open={isOpen} onClose={handleClose} className="relative z-[1000]">
      {/* Modal backdrop */}
      <div className="fixed inset-0 bg-[#000]/50" aria-hidden="true" />

      <div className="fixed inset-0 flex items-center justify-center p-4">
        <Dialog.Panel className="mx-auto w-full max-w-md rounded-lg bg-white dark:bg-neutral-800 p-6 shadow-xl border border-neutral-200 dark:border-neutral-700">
          <Dialog.Title className="text-xl font-semibold mb-4 flex items-center">
            {isInvite ? (
              <>
                {i18n.t(k.YOU_HAVE_BEEN_INVITED_TO_JOIN)}{" "}
                {tenantInfo.number_of_users}
                {i18n.t(k.OTHER_TEAMMATE)}
                {tenantInfo.number_of_users === 1 ? "" : i18n.t(k.S)}{" "}
                {i18n.t(k.OF)} {APP_DOMAIN}
                {i18n.t(k._8)}
              </>
            ) : (
              <>
                {i18n.t(k.YOUR_REQUEST_TO_JOIN)} {tenantInfo.number_of_users}{" "}
                {i18n.t(k.OTHER_USERS_OF)} {APP_DOMAIN}{" "}
                {i18n.t(k.HAS_BEEN_APPROVED)}
              </>
            )}
          </Dialog.Title>

          <div className="space-y-4">
            {error && (
              <p className="text-red-500 dark:text-red-400 text-sm">{error}</p>
            )}

            <p className="text-sm text-neutral-600 dark:text-neutral-400">
              {isInvite ? (
                <>
                  {i18n.t(k.BY_ACCEPTING_THIS_INVITATION)} {APP_DOMAIN}{" "}
                  {i18n.t(k.TEAM_AND_LOSE_ACCESS_TO_YOUR_C)}
                  <br />
                  {i18n.t(k.NOTE_YOU_WILL_LOSE_ACCESS_TO)}
                </>
              ) : (
                <>
                  {i18n.t(k.TO_FINISH_JOINING_YOUR_TEAM_P)}{" "}
                  <em>{user?.email}</em>
                  {i18n.t(k._8)}
                </>
              )}
            </p>

            <div
              className={`flex ${
                isInvite ? "justify-between" : "justify-center"
              } w-full pt-2 gap-4`}
            >
              {isInvite && (
                <Button
                  onClick={handleRejectInvite}
                  variant="outline"
                  className="flex items-center flex-1"
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <span className="animate-spin mr-2">{i18n.t(k._20)}</span>
                  ) : (
                    <X className="mr-2 h-4 w-4" />
                  )}
                  {i18n.t(k.DECLINE)}
                </Button>
              )}

              <Button
                variant="agent"
                onClick={handleJoinTenant}
                className={`flex items-center justify-center ${
                  isInvite ? "flex-1" : "w-full"
                }`}
                disabled={isLoading}
              >
                {isLoading ? (
                  <span className="flex items-center">
                    <span className="animate-spin mr-2">{i18n.t(k._20)}</span>
                    {isInvite ? i18n.t(k.ACCEPTING) : i18n.t(k.JOINING)}
                  </span>
                ) : (
                  <>
                    {isInvite
                      ? i18n.t(k.ACCEPT_INVITATION)
                      : i18n.t(k.REAUTHENTICATE)}
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </>
                )}
              </Button>
            </div>
          </div>
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}
