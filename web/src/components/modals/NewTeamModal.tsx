"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Button from "@/refresh-components/buttons/Button";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useUser } from "../user/UserProvider";
import SvgArrowRight from "@/icons/arrow-right";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import SvgArrowUp from "@/icons/arrow-up";
import { useModalProvider } from "@/refresh-components/contexts/ModalContext";
import SvgCheckCircle from "@/icons/check-circle";
import SvgOrganization from "@/icons/organization";
import Modal from "@/refresh-components/modals/Modal";

interface TenantByDomainResponse {
  tenant_id: string;
  number_of_users: number;
  creator_email: string;
}

export default function NewTeamModal() {
  const modal = useModalProvider();
  const [existingTenant, setExistingTenant] =
    useState<TenantByDomainResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [hasRequestedInvite, setHasRequestedInvite] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { user } = useUser();
  const appDomain = user?.email.split("@")[1];
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setPopup } = usePopup();

  useEffect(() => {
    const hasNewTeamParam = searchParams?.has("new_team");
    if (hasNewTeamParam) {
      modal.toggle(true);
      fetchTenantInfo();

      // Remove the new_team parameter from the URL without page reload
      const newParams = new URLSearchParams(searchParams?.toString() || "");
      newParams.delete("new_team");
      const newUrl =
        window.location.pathname +
        (newParams.toString() ? `?${newParams.toString()}` : "");
      window.history.replaceState({}, "", newUrl);
    }
  }, [searchParams, modal.toggle]);

  async function fetchTenantInfo() {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/tenants/existing-team-by-domain");
      if (!response.ok) {
        throw new Error(`Failed to fetch team info: ${response.status}`);
      }
      const responseJson = await response.json();
      if (!responseJson) {
        modal.toggle(false);
        setExistingTenant(null);
        return;
      }

      const data = responseJson as TenantByDomainResponse;
      setExistingTenant(data);
    } catch (error) {
      console.error("Failed to fetch tenant info:", error);
      setError("Could not retrieve team information. Please try again later.");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleRequestInvite() {
    if (!existingTenant) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const response = await fetch("/api/tenants/users/invite/request", {
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
  }

  function handleContinueToNewOrg() {
    const newUrl = window.location.pathname;
    router.replace(newUrl);
    modal.toggle(false);
  }

  if (!modal.isOpen || isLoading) return null;

  return (
    <modal.Provider>
      <Modal
        icon={hasRequestedInvite ? SvgCheckCircle : SvgOrganization}
        title={
          hasRequestedInvite
            ? "Join Request Sent"
            : `We found an existing team for ${appDomain}`
        }
        xs
      >
        <div className="p-4">
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
                  onClick={handleContinueToNewOrg}
                  className="w-full"
                  rightIcon={SvgArrowRight}
                >
                  Continue with new team
                </Button>
              </div>
            </div>
          ) : hasRequestedInvite ? (
            <div className="space-y-4">
              <p className="text-neutral-700 dark:text-neutral-200">
                Your join request has been sent. You can explore as your own
                team while waiting for an admin of {appDomain} to approve your
                request.
              </p>
              <div className="flex w-full pt-2">
                <Button
                  onClick={handleContinueToNewOrg}
                  className="w-full"
                  rightIcon={SvgArrowRight}
                >
                  Try Onyx while waiting
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-neutral-500 dark:text-neutral-200 text-sm mb-2">
                Your join request can be approved by any admin of {appDomain}.
              </p>
              <div className="mt-4">
                <Button
                  onClick={handleRequestInvite}
                  className="w-full"
                  disabled={isSubmitting}
                  leftIcon={isSubmitting ? SimpleLoader : SvgArrowUp}
                >
                  {isSubmitting
                    ? "Sending request..."
                    : "Request to join your team"}
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
        </div>
      </Modal>
    </modal.Provider>
  );
}
