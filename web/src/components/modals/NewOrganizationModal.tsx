"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Dialog } from "@headlessui/react";
import { Button } from "../ui/button";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Building, Users, ArrowRight, Send, CheckCircle } from "lucide-react";

interface TenantInfo {
  tenant_id: string;
  number_of_users: number;
  creator_email: string;
}

interface TenantByDomainResponse {
  tenant_id: string;
  number_of_users: number;
  creator_email: string;
}

export function NewOrganizationModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [existingTenant, setExistingTenant] =
    useState<TenantByDomainResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasRequestedInvite, setHasRequestedInvite] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setPopup } = usePopup();

  useEffect(() => {
    const hasNewOrgParam = searchParams.has("new_organization");
    if (hasNewOrgParam) {
      setIsOpen(true);
      fetchTenantInfo();
    }
  }, [searchParams]);

  const fetchTenantInfo = async () => {
    setIsLoading(true);
    try {
      const response2 = await fetch("/api/me");
      const me = await response2.json();

      const response3 = await fetch("/api/tenants/anonymous-user-path");

      const response = await fetch("/api/tenants/anonymous-user-path2");

      if (response.ok) {
        const data = (await response.json()) as TenantByDomainResponse;
        setExistingTenant(data);
      }
    } catch (error) {
      console.error("Failed to fetch tenant info:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRequestInvite = async () => {
    try {
      if (!existingTenant) return;

      // Call the API to request an invite
      const response = await fetch("/api/tenants/request-invite", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tenant_id: existingTenant.tenant_id }),
      });

      if (!response.ok) {
        throw new Error("Failed to request invite");
      }

      setHasRequestedInvite(true);
      setPopup({
        message: "Your invite request has been sent to the organization admin.",
        type: "success",
      });
    } catch (error) {
      setPopup({
        message: "Failed to request an invite. Please try again.",
        type: "error",
      });
    }
  };

  const handleContinueToNewOrg = () => {
    // Remove the new_organization parameter and close the modal
    const newUrl = window.location.pathname;
    router.replace(newUrl);
    setIsOpen(false);
  };

  // Note: We've removed the handleContinueToExistingOrg function as per requirements
  // to never show both "Continue to existing" and "Continue to new" organization options

  if (!isOpen) return null;

  return (
    <Dialog open={isOpen} onClose={() => {}} className="relative z-50">
      <div className="fixed inset-0 bg-black/50" aria-hidden="true" />

      <div className="fixed inset-0 flex items-center justify-center p-4">
        <Dialog.Panel className="mx-auto w-full max-w-md rounded-lg bg-white dark:bg-gray-800 p-6 shadow-xl border border-gray-200 dark:border-gray-700">
          <Dialog.Title className="text-xl font-semibold mb-4 flex items-center">
            {hasRequestedInvite ? (
              <>
                <CheckCircle className="mr-2 h-5 w-5 text-green-500" /> Invite
                Requested
              </>
            ) : (
              <>
                <Building className="mr-2 h-5 w-5" /> Welcome to Your
                Organization
              </>
            )}
          </Dialog.Title>

          {isLoading ? (
            <div className="py-8 text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 dark:border-gray-100 mx-auto mb-4"></div>
              <p>Loading organization information...</p>
            </div>
          ) : hasRequestedInvite ? (
            <div className="space-y-4">
              <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-100 dark:border-green-800">
                <p className="text-green-800 dark:text-green-200">
                  Your invite request has been sent. Play around in your own
                  organization while you wait for approval.
                </p>
              </div>
              <div className="flex justify-center pt-2">
                <Button
                  onClick={handleContinueToNewOrg}
                  className="flex items-center"
                >
                  Continue to your new organization
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {existingTenant ? (
                <>
                  <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-100 dark:border-blue-800">
                    <p className="text-blue-800 dark:text-blue-200 mb-2">
                      We found an organization with your email domain:
                    </p>
                    <div className="flex items-center text-sm text-blue-700 dark:text-blue-300 mb-1">
                      <Users className="mr-2 h-4 w-4" />
                      <span>{existingTenant.number_of_users} users</span>
                    </div>
                    <div className="flex items-center text-sm text-blue-700 dark:text-blue-300">
                      <span className="mr-2">👤</span>
                      <span>Created by {existingTenant.creator_email}</span>
                    </div>
                  </div>
                  <p className="font-medium">Would you like to:</p>
                  <div className="flex flex-col space-y-3 pt-2">
                    <Button
                      onClick={handleRequestInvite}
                      variant="outline"
                      className="flex items-center justify-center"
                    >
                      <Send className="mr-2 h-4 w-4" />
                      Ask for an invite to this organization
                    </Button>
                    <Button
                      onClick={handleContinueToNewOrg}
                      variant="secondary"
                      className="flex items-center justify-center"
                    >
                      <Building className="mr-2 h-4 w-4" />
                      Continue to your new organization
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-lg border border-green-100 dark:border-green-800">
                    <p className="text-green-800 dark:text-green-200">
                      Welcome to your new organization! You're all set to get
                      started.
                    </p>
                  </div>
                  <div className="flex justify-center pt-2">
                    <Button
                      onClick={handleContinueToNewOrg}
                      className="flex items-center"
                    >
                      Continue to your new organization
                      <ArrowRight className="ml-2 h-4 w-4" />
                    </Button>
                  </div>
                </>
              )}
            </div>
          )}
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}
