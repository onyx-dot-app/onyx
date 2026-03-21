"use client";

import { useState } from "react";
import Link from "next/link";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { logout } from "@/lib/user";
import { loadStripe } from "@stripe/stripe-js";
import {
  DEFAULT_APPLICATION_NAME,
  NEXT_PUBLIC_CLOUD_ENABLED,
} from "@/lib/constants";
import { useLicense } from "@/hooks/useLicense";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { ApplicationStatus } from "@/interfaces/settings";
import Text from "@/refresh-components/texts/Text";
import { SvgLock } from "@opal/icons";

const linkClassName = "text-action-link-05 hover:text-action-link-06 underline";

const fetchStripePublishableKey = async (): Promise<string> => {
  const response = await fetch("/api/tenants/stripe-publishable-key");
  if (!response.ok) {
    throw new Error("Failed to fetch Stripe publishable key");
  }
  const data = await response.json();
  return data.publishable_key;
};

const fetchResubscriptionSession = async () => {
  const response = await fetch("/api/tenants/create-subscription-session", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });
  if (!response.ok) {
    throw new Error("Failed to create resubscription session");
  }
  return response.json();
};

export default function AccessRestricted() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: license } = useLicense();
  const settings = useSettingsContext();

  const isSeatLimitExceeded =
    settings.settings.application_status ===
    ApplicationStatus.SEAT_LIMIT_EXCEEDED;
  const hadPreviousLicense = license?.has_license === true;
  const showRenewalMessage = NEXT_PUBLIC_CLOUD_ENABLED || hadPreviousLicense;
  const applicationName =
    settings.enterpriseSettings?.application_name?.trim() ||
    DEFAULT_APPLICATION_NAME;

  function getSeatLimitMessage() {
    const { used_seats, seat_count } = settings.settings;
    const counts =
      used_seats != null && seat_count != null
        ? ` (${used_seats} users / ${seat_count} seats)`
        : "";
    return `Your organization has exceeded its licensed seat count${counts}. Access is restricted until the number of users is reduced or your license is upgraded.`;
  }

  const initialModalMessage = isSeatLimitExceeded
    ? getSeatLimitMessage()
    : showRenewalMessage
      ? NEXT_PUBLIC_CLOUD_ENABLED
        ? `Tu acceso a ${applicationName} se suspendió temporalmente por un problema con tu suscripción.`
        : `Tu acceso a ${applicationName} se suspendió temporalmente por un problema con tu licencia.`
      : `Se requiere una licencia Enterprise para usar ${applicationName}. Tus datos están protegidos y volverán a estar disponibles cuando se active una licencia.`;

  const handleResubscribe = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const publishableKey = await fetchStripePublishableKey();
      const { sessionId } = await fetchResubscriptionSession();
      const stripe = await loadStripe(publishableKey);

      if (stripe) {
        await stripe.redirectToCheckout({ sessionId });
      } else {
        throw new Error("Stripe failed to load");
      }
    } catch (error) {
      console.error("Error creating resubscription session:", error);
      setError("Error opening resubscription page. Please try again later.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <ErrorPageLayout>
      <div className="flex items-center gap-2">
        <Text headingH2>Access Restricted</Text>
        <SvgLock className="stroke-status-error-05 w-[1.5rem] h-[1.5rem]" />
      </div>

      <Text text03>{initialModalMessage}</Text>

      {isSeatLimitExceeded ? (
        <>
          <Text text03>
            If you are an administrator, you can manage users on the{" "}
            <Link className={linkClassName} href="/admin/users">
              User Management
            </Link>{" "}
            page or upgrade your license on the{" "}
            <Link className={linkClassName} href="/admin/billing">
              Admin Billing
            </Link>{" "}
            page.
          </Text>

          <div className="flex flex-row gap-2">
            <Button
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              Log out
            </Button>
          </div>
        </>
      ) : NEXT_PUBLIC_CLOUD_ENABLED ? (
        <>
          <Text text03>
            {`Para recuperar el acceso y seguir aprovechando ${applicationName}, actualiza tu información de pago.`}
          </Text>

          <Text text03>
            Si eres administrador, puedes gestionar la suscripción con el botón
            de abajo. Si no, contacta a tu administrador para resolverlo.
          </Text>

          <div className="flex flex-row gap-2">
            <Disabled disabled={isLoading}>
              <Button onClick={handleResubscribe}>
                {isLoading ? "Cargando..." : "Reactivar suscripción"}
              </Button>
            </Disabled>
            <Button
              prominence="secondary"
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              Cerrar sesión
            </Button>
          </div>

          {error && <Text className="text-status-error-05">{error}</Text>}
        </>
      ) : (
        <>
          <Text text03>
            {hadPreviousLicense
              ? `Para recuperar tu acceso y seguir usando ${applicationName}, contacta a tu administrador para renovar la licencia.`
              : "Para comenzar, contacta a tu administrador del sistema para obtener una licencia Enterprise."}
          </Text>

          <Text text03>
            Si eres administrador, visita la página de{" "}
            <Link className={linkClassName} href="/admin/billing">
              Admin Billing
            </Link>{" "}
            para {hadPreviousLicense ? "renovar" : "activar"} la licencia,
            completar el alta con Stripe o escribir a{" "}
            <a className={linkClassName} href="mailto:contact@activa.ai">
              contact@activa.ai
            </a>{" "}
            si necesitas ayuda con facturación.
          </Text>

          <div className="flex flex-row gap-2">
            <Button
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              Cerrar sesión
            </Button>
          </div>
        </>
      )}

      <Text text03>
        ¿Necesitas ayuda? Únete a nuestra{" "}
        <InlineExternalLink
          className={linkClassName}
          href="https://discord.gg/4NA5SbzrWb"
        >
          comunidad de Discord
        </InlineExternalLink>{" "}
        para recibir soporte.
      </Text>
    </ErrorPageLayout>
  );
}
