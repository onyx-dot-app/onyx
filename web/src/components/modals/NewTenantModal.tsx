"use client";

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
}

export default function NewTenantModal({
  tenantInfo,
  isInvite = false,
}: NewTenantModalProps) {
  const router = useRouter();
  const { setPopup } = usePopup();
  const { user } = useUser();
  const [isOpen, setIsOpen] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleJoinTenant = async () => {
    setIsLoading(true);
    setError(null);

    try {
      if (isInvite) {
        // Accept the invitation through the API
        const response = await fetch("/api/tenants/users/accept-invite", {
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
      router.push(`/auth/join?email=${user?.email}`);
      setIsOpen(false);
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
      const response = await fetch("/api/tenants/users/deny-invite", {
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
      setIsOpen(false);
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
    <Dialog
      open={isOpen}
      onClose={() => {
        setIsOpen(false);
      }}
      className="relative z-[1000]"
    >
      {/* Modal backdrop */}
      <div className="fixed inset-0 bg-[#000]/50" aria-hidden="true" />

      <div className="fixed inset-0 flex items-center justify-center p-4">
        <Dialog.Panel className="mx-auto w-full max-w-md rounded-lg bg-white dark:bg-neutral-800 p-6 shadow-xl border border-neutral-200 dark:border-neutral-700">
          <Dialog.Title className="text-xl font-semibold mb-4 flex items-center">
            {isInvite ? (
              <>
                You have been invited to join an {APP_DOMAIN} team with{" "}
                {tenantInfo.number_of_users} users.
              </>
            ) : (
              <>
                Your request to join an {APP_DOMAIN} team with{" "}
                {tenantInfo.number_of_users + 4} users has been approved.
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
                  By accepting this invitation, you&apos;ll join the team and
                  have access to all shared resources. You can collaborate with
                  other members using your email {user?.email}.
                </>
              ) : (
                <>
                  To finish joining the team, you&apos;ll need to create a new
                  account with your email, <em>{user?.email}</em>.
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
                    <span className="animate-spin mr-2">⟳</span>
                  ) : (
                    <X className="mr-2 h-4 w-4" />
                  )}
                  Decline
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
                    <span className="animate-spin mr-2">⟳</span>
                    {isInvite ? "Accepting..." : "Joining..."}
                  </span>
                ) : (
                  <>
                    {isInvite ? "Accept Invitation" : "Join Organization"}
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
