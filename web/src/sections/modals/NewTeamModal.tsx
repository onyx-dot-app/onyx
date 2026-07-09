"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { Button, Text } from "@opal/components";
import { InputErrorText } from "@opal/layouts";
import Modal from "@/refresh-components/Modal";
import { toast } from "@/hooks/useToast";
import { useUser } from "@/providers/UserProvider";
import { useModalContext } from "@/components/context/ModalContext";
import {
  SvgArrowRight,
  SvgArrowUp,
  SvgCheckCircle,
  SvgOrganization,
  SvgPlus,
  SvgSimpleLoader,
} from "@opal/icons";
export interface TenantByDomainResponse {
  tenant_id: string;
  number_of_users: number;
  creator_email: string;
}

export default function NewTeamModal() {
  const { showNewTeamModal, setShowNewTeamModal } = useModalContext();
  const [existingTenant, setExistingTenant] =
    useState<TenantByDomainResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [hasRequestedInvite, setHasRequestedInvite] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { user } = useUser();
  const appDomain = user?.email.split("@")[1] ?? "";
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const hasNewTeamParam = searchParams?.has("new_team");
    if (hasNewTeamParam) {
      setShowNewTeamModal(true);
      fetchTenantInfo();

      // Remove the new_team parameter from the URL without page reload
      const newParams = new URLSearchParams(searchParams?.toString() || "");
      newParams.delete("new_team");
      const newUrl =
        window.location.pathname +
        (newParams.toString() ? `?${newParams.toString()}` : "");
      window.history.replaceState({}, "", newUrl);
    }
  }, [searchParams, setShowNewTeamModal]);

  const fetchTenantInfo = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/tenants/existing-team-by-domain");
      if (!response.ok) {
        throw new Error(`Failed to fetch team info: ${response.status}`);
      }
      const responseJson = await response.json();
      if (!responseJson) {
        setShowNewTeamModal(false);
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
  };

  const handleRequestInvite = async () => {
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
        throw new Error(
          errorData.detail || errorData.message || "Failed to request invite"
        );
      }

      setHasRequestedInvite(true);
      toast.success("Your invite request has been sent to the team admin.");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to request an invite";
      setError(message);
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleContinueToNewOrg = () => {
    const newUrl = window.location.pathname;
    router.replace(newUrl as Route);
    setShowNewTeamModal(false);
  };

  // Update the close handler to use the context
  const handleClose = () => {
    setShowNewTeamModal(false);
  };

  // Only render if showNewTeamModal is true
  if (!showNewTeamModal || isLoading) return null;

  const headerIcon = hasRequestedInvite ? SvgCheckCircle : SvgOrganization;
  const headerTitle = hasRequestedInvite
    ? "Join Request Sent"
    : `We found an existing team for ${appDomain}`;

  return (
    <Modal
      open={showNewTeamModal}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <Modal.Content width="sm" preventAccidentalClose={false}>
        <Modal.Header
          icon={headerIcon}
          title={headerTitle}
          onClose={handleClose}
        />

        <Modal.Body>
          {error ? (
            <InputErrorText>{error}</InputErrorText>
          ) : hasRequestedInvite ? (
            <Text font="main-ui-body" color="text-04">
              {`Your join request has been sent. You can explore as your own team while waiting for an admin of ${appDomain} to approve your request.`}
            </Text>
          ) : (
            <Text font="main-ui-body" color="text-03">
              {`Your join request can be approved by any admin of ${appDomain}.`}
            </Text>
          )}
        </Modal.Body>

        <Modal.Footer flexDirection="column" alignItems="stretch">
          {error ? (
            <Button
              onClick={handleContinueToNewOrg}
              width="full"
              rightIcon={SvgArrowRight}
            >
              Continue with new team
            </Button>
          ) : hasRequestedInvite ? (
            <Button
              onClick={handleContinueToNewOrg}
              width="full"
              rightIcon={SvgArrowRight}
            >
              Try Onyx while waiting
            </Button>
          ) : (
            <>
              <Button
                disabled={isSubmitting}
                onClick={handleRequestInvite}
                width="full"
                icon={isSubmitting ? SvgSimpleLoader : SvgArrowUp}
              >
                {isSubmitting
                  ? "Sending request..."
                  : "Request to join your team"}
              </Button>
              <Button
                onClick={handleContinueToNewOrg}
                width="full"
                icon={SvgPlus}
                prominence="secondary"
              >
                Continue with new team
              </Button>
            </>
          )}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
