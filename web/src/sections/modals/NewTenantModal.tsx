"use client";

import { useState } from "react";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import { toast } from "@/hooks/useToast";
import { SvgArrowRight, SvgUsers, SvgX } from "@opal/icons";
import { logout } from "@/lib/user";
import { useUser } from "@/providers/UserProvider";
import { NewTenantInfo } from "@/lib/types";
import { useRouter } from "next/navigation";
import Text from "@/refresh-components/texts/Text";
import { ErrorTextLayout } from "@/layouts/input-layouts";

// App domain should not be hardcoded
const APP_DOMAIN = process.env.NEXT_PUBLIC_APP_DOMAIN || "onyx.app";

export interface NewTenantModalProps {
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
  const { user } = useUser();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleJoinTenant() {
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

        toast.success("You have accepted the invitation.");
      } else {
        // For non-invite flow, just show success message
        toast.success("Processing your team join request...");
      }

      // Common logout and redirect for both flows
      await logout();
      router.push(`/auth/join?email=${encodeURIComponent(user?.email || "")}`);
      onClose?.();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to join the team. Please try again.";

      setError(message);
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleRejectInvite() {
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

      toast.info("You have declined the invitation.");
      onClose?.();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to decline the invitation. Please try again.";

      setError(message);
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  }

  const title = isInvite
    ? `You have been invited to join ${
        tenantInfo.number_of_users
      } other teammate${
        tenantInfo.number_of_users === 1 ? "" : "s"
      } of ${APP_DOMAIN}.`
    : `Your request to join ${tenantInfo.number_of_users} other users of ${APP_DOMAIN} has been approved.`;

  const description = isInvite
    ? `By accepting this invitation, you will join the existing ${APP_DOMAIN} team and lose access to your current team. Note: you will lose access to your current agents, prompts, chats, and connected sources.`
    : `To finish joining your team, please reauthenticate with ${user?.email}.`;

  return (
    <Modal open>
      <Modal.Content width="sm" height="sm" preventAccidentalClose={false}>
        <Modal.Header icon={SvgUsers} title={title} onClose={onClose} />

        <Modal.Body>
          <Text>{description}</Text>
          {error && <ErrorTextLayout>{error}</ErrorTextLayout>}
        </Modal.Body>

        <Modal.Footer>
          <BasicModalFooter
            cancel={
              isInvite ? (
                <Button
                  onClick={handleRejectInvite}
                  secondary
                  disabled={isLoading}
                  leftIcon={SvgX}
                >
                  Decline
                </Button>
              ) : undefined
            }
            submit={
              <Button
                onClick={handleJoinTenant}
                disabled={isLoading}
                rightIcon={SvgArrowRight}
              >
                {isLoading
                  ? isInvite
                    ? "Accepting..."
                    : "Joining..."
                  : isInvite
                    ? "Accept Invitation"
                    : "Reauthenticate"}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
