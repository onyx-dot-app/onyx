"use client";

import { useState } from "react";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { toast } from "@/hooks/useToast";
import { SvgArrowRight, SvgUsers, SvgX } from "@opal/icons";
import { logout } from "@/lib/user";
import { useUser } from "@/providers/UserProvider";
import { NewTenantInfo } from "@/lib/types";
import { useRouter } from "next/navigation";
import Text from "@/refresh-components/texts/Text";
import { ErrorTextLayout } from "@/layouts/input-layouts";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { DEFAULT_APPLICATION_NAME } from "@/lib/constants";

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
  const settings = useSettingsContext();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const applicationName =
    settings?.enterpriseSettings?.application_name?.trim() ||
    DEFAULT_APPLICATION_NAME;

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
              "No se pudo aceptar la invitación"
          );
        }

        toast.success("Aceptaste la invitación.");
      } else {
        // For non-invite flow, just show success message
        toast.success("Estamos procesando tu solicitud para unirte al equipo...");
      }

      // Common logout and redirect for both flows
      await logout();
      router.push(`/auth/join?email=${encodeURIComponent(user?.email || "")}`);
      onClose?.();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "No se pudo unir al equipo. Inténtalo de nuevo.";

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
            "No se pudo rechazar la invitación"
        );
      }

      toast.info("Rechazaste la invitación.");
      onClose?.();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "No se pudo rechazar la invitación. Inténtalo de nuevo.";

      setError(message);
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  }

  const title = isInvite
    ? `Te invitaron a unirte a ${
        tenantInfo.number_of_users
      } integrante${
        tenantInfo.number_of_users === 1 ? "" : "s"
      } más del equipo de ${applicationName}.`
    : `Se aprobó tu solicitud para unirte a ${tenantInfo.number_of_users} usuario${
        tenantInfo.number_of_users === 1 ? "" : "s"
      } más del equipo de ${applicationName}.`;

  const description = isInvite
    ? `Al aceptar esta invitación, te unirás al equipo actual de ${applicationName} y perderás acceso a tu equipo actual. Ten en cuenta que perderás acceso a tus agentes, prompts, chats y fuentes conectadas actuales.`
    : `Para terminar de unirte al equipo, vuelve a autenticarte con ${user?.email}.`;

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
                <Disabled disabled={isLoading}>
                  <Button
                    prominence="secondary"
                    onClick={handleRejectInvite}
                    icon={SvgX}
                  >
                    Rechazar
                  </Button>
                </Disabled>
              ) : undefined
            }
            submit={
              <Disabled disabled={isLoading}>
                <Button onClick={handleJoinTenant} rightIcon={SvgArrowRight}>
                  {isLoading
                    ? isInvite
                      ? "Aceptando..."
                      : "Uniéndote..."
                    : isInvite
                      ? "Aceptar invitación"
                      : "Volver a autenticarme"}
                </Button>
              </Disabled>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
