"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Dialog } from "@headlessui/react";
import { Button } from "../ui/button";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Building, ArrowRight, Send, CheckCircle } from "lucide-react";

// Define types for API responses
interface TenantByDomainResponse {
  tenant_id: string;
  number_of_users: number;
  creator_email: string;
}

// App domain should not be hardcoded
const APP_DOMAIN = process.env.NEXT_PUBLIC_APP_DOMAIN || "onyx.app";

export function NewTeamModal() {
  const [isOpen, setIsOpen] = useState(false);
  const [existingTenant, setExistingTenant] =
    useState<TenantByDomainResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [hasRequestedInvite, setHasRequestedInvite] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const router = useRouter();
  const searchParams = useSearchParams();
  const { setPopup } = usePopup();

  useEffect(() => {
    const hasNewTeamParam = searchParams.has("new_team");
    if (hasNewTeamParam) {
      setIsOpen(true);
      fetchTenantInfo();

      // Remove the new_team parameter from the URL without page reload
      const newParams = new URLSearchParams(searchParams.toString());
      newParams.delete("new_team");
      const newUrl =
        window.location.pathname +
        (newParams.toString() ? `?${newParams.toString()}` : "");
      window.history.replaceState({}, "", newUrl);
    }
  }, [searchParams]);

  const fetchTenantInfo = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/tenants/existing-team-by-domain");
      if (!response.ok) {
        throw new Error(`Failed to fetch team info: ${response.status}`);
      }

      const data = (await response.json()) as TenantByDomainResponse;
      setExistingTenant(data);
    } catch (error) {
      console.error("Failed to fetch tenant info:", error);
      setError("Could not retrieve team information. Please try again later.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleRequestInvite = async () => {
    if (!existingTenant) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const response = await fetch("/api/tenants/request-invite", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tenant_id: existingTenant.tenant_id }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || "Failed to request invite");
      }

      setHasRequestedInvite(true);
      setPopup({
        message: "Your invite request has been sent to the team admin.",
        type: "success",
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to request an invite";
      setError(message);
      setPopup({
        message,
        type: "error",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleContinueToNewOrg = () => {
    const newUrl = window.location.pathname;
    router.replace(newUrl);
    setIsOpen(false);
  };

  // Don't render if not open or no tenant found
  if (!isOpen || (!existingTenant && !isLoading && !error)) return null;

  return (
    <Dialog open={isOpen} onClose={() => {}} className="relative z-[1000]">
      {/* Modal backdrop */}
      <div className="fixed inset-0 bg-[#000]/50" aria-hidden="true" />

      <div className="fixed inset-0 flex items-center justify-center p-4">
        <Dialog.Panel className="mx-auto w-full max-w-md rounded-lg bg-white dark:bg-neutral-800 p-6 shadow-xl border border-neutral-200 dark:border-neutral-700">
          <Dialog.Title className="text-xl font-semibold mb-4 flex items-center">
            {hasRequestedInvite ? (
              <>
                <CheckCircle className="mr-2 h-5 w-5 text-neutral-900 dark:text-[#fff]" />
                Join Request Sent
              </>
            ) : (
              <>
                <Building className="mr-2 h-5 w-5" />
                We found an existing team for {APP_DOMAIN}
              </>
            )}
          </Dialog.Title>

          {isLoading ? (
            <div className="py-8 text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-neutral-900 dark:border-neutral-100 mx-auto mb-4"></div>
              <p>Loading team information...</p>
            </div>
          ) : error ? (
            <div className="space-y-4">
              <p className="text-red-500 dark:text-red-400">{error}</p>
              <div className="flex w-full pt-2">
                <Button
                  variant="agent"
                  onClick={handleContinueToNewOrg}
                  className="flex w-full text-center items-center justify-center"
                >
                  Continue with new team
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
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
                  className="flex w-full text-center items-center justify-center"
                >
                  Continue to try Onyx
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-neutral-500 dark:text-neutral-200 text-sm mb-2">
                Your request can be approved by any admin of {APP_DOMAIN}.
              </p>
              <div className="mt-4">
                <Button
                  onClick={handleRequestInvite}
                  variant="agent"
                  className="flex w-full items-center justify-center"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? (
                    <span className="flex items-center">
                      <span className="animate-spin mr-2">⟳</span>
                      Sending request...
                    </span>
                  ) : (
                    <>
                      <Send className="mr-2 h-4 w-4" />
                      Request to join your team
                    </>
                  )}
                </Button>
              </div>
              <div
                onClick={handleContinueToNewOrg}
                className="flex hover:underline cursor-pointer text-link text-sm flex-col space-y-3 pt-0"
              >
                + Continue with new team
              </div>
            </div>
          )}
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}
