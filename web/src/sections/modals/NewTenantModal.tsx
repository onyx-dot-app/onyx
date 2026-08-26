"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { BasicModalFooter, Modal } from "@opal/components";
import { Button } from "@opal/components";
import { SvgArrowRight, SvgUsers, SvgX } from "@opal/icons";
import { logout } from "@/lib/users/svc";
import { useUser } from "@/providers/UserProvider";
import { NewTenantInfo } from "@/lib/types";
import { useRouter } from "next/navigation";
import Text from "@/refresh-components/texts/Text";
import { InputErrorText, toast } from "@opal/layouts";

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
  const t = useTranslations("admin.modals.newTenant");
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
          throw new Error(
            errorData.detail ||
              errorData.message ||
              t("acceptError.responseFallback")
          );
        }

        toast.success(t("acceptedToast.message"));
      } else {
        // For non-invite flow, just show success message
        toast.success(t("joinRequestToast.message"));
      }

      // Common logout and redirect for both flows
      await logout();
      router.push(`/auth/join?email=${encodeURIComponent(user?.email || "")}`);
      onClose?.();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("joinError.message");

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
        throw new Error(
          errorData.detail ||
            errorData.message ||
            t("declineError.responseFallback")
        );
      }

      toast.info(t("declinedToast.message"));
      onClose?.();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("declineError.message");

      setError(message);
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  }

  const title = isInvite
    ? t("inviteTitle", {
        count: tenantInfo.number_of_users,
        domain: APP_DOMAIN,
      })
    : t("approvedTitle", {
        count: tenantInfo.number_of_users,
        domain: APP_DOMAIN,
      });

  const description = isInvite
    ? t("inviteDescription", { domain: APP_DOMAIN })
    : t("reauthenticateDescription", { email: user?.email ?? "" });

  return (
    <Modal open>
      <Modal.Content width="sm" height="sm" preventAccidentalClose={false}>
        <Modal.Header icon={SvgUsers} title={title} onClose={onClose} />

        <Modal.Body>
          <Text>{description}</Text>
          {error && <InputErrorText>{error}</InputErrorText>}
        </Modal.Body>

        <Modal.Footer>
          <BasicModalFooter
            cancel={
              isInvite ? (
                <Button
                  disabled={isLoading}
                  prominence="secondary"
                  onClick={handleRejectInvite}
                  icon={SvgX}
                >
                  {t("declineButton.label")}
                </Button>
              ) : undefined
            }
            submit={
              <Button
                disabled={isLoading}
                onClick={handleJoinTenant}
                rightIcon={SvgArrowRight}
              >
                {isLoading
                  ? isInvite
                    ? t("submitButton.acceptingLabel")
                    : t("submitButton.joiningLabel")
                  : isInvite
                    ? t("submitButton.acceptLabel")
                    : t("submitButton.reauthenticateLabel")}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
