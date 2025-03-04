"use client";

import { useState } from "react";
import { Dialog } from "@headlessui/react";
import { Button } from "../ui/button";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Building, ArrowRight, CheckCircle, X } from "lucide-react";
import { logout } from "@/lib/user";
import { useUser } from "../user/UserProvider";
import { NewTenantInfo } from "@/lib/types";
import { useRouter } from "next/navigation";

export default function NewTenantModal({
  tenantInfo,
  isInvite = false,
}: {
  tenantInfo: NewTenantInfo;
  isInvite?: boolean;
}) {
  const router = useRouter();
  const { setPopup } = usePopup();
  const { user } = useUser();
  const [isOpen, setIsOpen] = useState(true);
  const [isLoading, setIsLoading] = useState(false);

  const handleJoinTenant = async () => {
    setIsLoading(true);
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
          throw new Error("Failed to accept invitation");
        }

        setPopup({
          message: "You have accepted the invitation.",
          type: "success",
        });
      } else {
        // For non-invite flow, log out and redirect to signup
        await logout();
        router.push(`/auth/signup?email=${user?.email}`);
      }
      await logout();
      setIsOpen(false);
    } catch (error) {
      setPopup({
        message: "Failed to join the organization. Please try again.",
        type: "error",
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleRejectInvite = async () => {
    if (!isInvite) return;

    setIsLoading(true);
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
        throw new Error("Failed to decline invitation");
      }

      setPopup({
        message: "You have declined the invitation.",
        type: "info",
      });
      setIsOpen(false);
    } catch (error) {
      setPopup({
        message: "Failed to decline the invitation. Please try again.",
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
      <div className="fixed inset-0 bg-[#000]/50" aria-hidden="true" />

      <div className="fixed inset-0 flex items-center justify-center p-4">
        <Dialog.Panel className="mx-auto w-full max-w-md rounded-lg bg-white dark:bg-gray-800 p-6 shadow-xl border border-gray-200 dark:border-gray-700">
          <Dialog.Title className="text-xl font-semibold mb-4 flex items-center">
            {isInvite ? (
              <>
                <Building className="mr-2 h-5 w-5" />
                Organization Invitation
              </>
            ) : (
              <>
                <CheckCircle className="mr-2 h-5 w-5 text-green-500" />
                Organization Joined
              </>
            )}
          </Dialog.Title>
          <div className="space-y-4">
            <div className="p-4 bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-700">
              {isInvite ? (
                <p className="text-gray-800 dark:text-gray-200 mb-2">
                  You have been invited to join{" "}
                  <span className="font-medium">{tenantInfo.tenant_id}</span>,
                  an organization with {tenantInfo.number_of_users} users.
                </p>
              ) : (
                <p className="text-gray-800 dark:text-gray-200 mb-2">
                  Your request to join an organization with{" "}
                  {tenantInfo.number_of_users} users has been approved. You will
                  now be part of this organization.
                </p>
              )}
            </div>

            <p className="text-sm text-gray-600 dark:text-gray-400">
              {isInvite ? (
                <>
                  By accepting this invitation, you'll join the organization and
                  have access to all shared resources. You can collaborate with
                  other members using your email {user?.email}.
                </>
              ) : (
                <>
                  To join this organization, you'll need to create a new account
                  with your email {user?.email}. Once you do, you'll
                  automatically be part of this organization and have access to
                  all its shared resources.
                </>
              )}
            </p>
            <div
              className={`flex ${
                isInvite ? "justify-between" : "justify-center"
              } w-full pt-4 gap-4`}
            >
              {isInvite && (
                <Button
                  onClick={handleRejectInvite}
                  variant="outline"
                  className="flex items-center flex-1"
                  disabled={isLoading}
                >
                  <X className="mr-2 h-4 w-4" />
                  Decline
                </Button>
              )}
              <Button
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
