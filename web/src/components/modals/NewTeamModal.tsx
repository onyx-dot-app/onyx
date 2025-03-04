"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Dialog } from "@headlessui/react";
import { Button } from "../ui/button";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Building, ArrowRight, Send, CheckCircle } from "lucide-react";

interface TenantByDomainResponse {
  tenant_id: string;
  number_of_users: number;
  creator_email: string;
}

export function NewTeamModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [existingTenant, setExistingTenant] =
    useState<TenantByDomainResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasRequestedInvite, setHasRequestedInvite] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setPopup } = usePopup();

  useEffect(() => {
    const hasNewOrgParam = searchParams.has("new_team");
    if (hasNewOrgParam) {
      setIsOpen(true);
      fetchTenantInfo();
    }
  }, [searchParams]);

  const fetchTenantInfo = async () => {
    setIsLoading(true);
    try {
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
        message: "Your invite request has been sent to the team admin.",
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
    const newUrl = window.location.pathname;
    router.replace(newUrl);
    setIsOpen(false);
  };

  if (!isOpen || !existingTenant) return null;

  return (
    <Dialog open={isOpen} onClose={() => {}} className="relative z-[1000]">
      <div className="fixed inset-0 bg-[#000]/50" aria-hidden="true" />

      <div className="fixed inset-0 flex items-center justify-center p-4">
        <Dialog.Panel className="mx-auto w-full max-w-md rounded-lg bg-white dark:bg-neutral-800 p-6 shadow-xl border border-neutral-200 dark:border-neutral-700">
          <Dialog.Title className="text-xl font-semibold mb-4 flex items-center">
            {hasRequestedInvite ? (
              <>
                <CheckCircle className="mr-2 h-5 w-5 text-neutral-900 dark:text-white" />
                Join Request Sent
              </>
            ) : (
              <>
                <Building className="mr-2 h-5 w-5" />
                We found an existing team for onyx.app
              </>
            )}
          </Dialog.Title>

          {isLoading ? (
            <div className="py-8 text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-neutral-900 dark:border-neutral-100 mx-auto mb-4"></div>
              <p>Loading team information...</p>
            </div>
          ) : hasRequestedInvite ? (
            <div className="space-y-4">
              <p className="text-neutral-700 dark:text-neutral-200">
                Your join request has been sent. You can explore on your own
                while waiting for the team admin to approve your request.
              </p>
              <div className="flex w-full pt-2">
                <Button
                  variant="agent"
                  onClick={handleContinueToNewOrg}
                  className="flex w-full text-center items-center"
                >
                  Continue to try Onyx
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-neutral-500 dark:text-neutral-200 text-sm mb-2">
                Your request can be approved by any admin of onyx.app.
              </p>
              <div className="mt-4">
                <p className="text-neutral-800 dark:text-neutral-200 mb-2"></p>
                <Button
                  onClick={handleRequestInvite}
                  variant="agent"
                  className="flex w-full items-center justify-center"
                >
                  <Send className="mr-2 h-4 w-4" />
                  Request to join your team
                </Button>
              </div>
              <div className="flex hover:underline cursor-pointer text-link text-sm flex-col space-y-3 pt-0">
                + Create new team
              </div>
            </div>
          )}
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}
