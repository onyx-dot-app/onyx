"use client";

import { useTranslations } from "next-intl";
import { getSourceDisplayName } from "@/lib/connectors/utils";
import OAuthCallbackPage from "@/components/oauth/OAuthCallbackPage";

export default function FederatedOAuthCallbackPage() {
  const t = useTranslations("admin.federatedCallback");
  const federatedConfig = {
    processingMessage: t("processing.title"),
    processingDetails: t("processing.details"),
    successMessage: t("success.title"),
    successDetailsTemplate: t.raw("success.detailsTemplate"),
    errorMessage: t("error.title"),
    backButtonText: t("backButton.label"),
    redirectingMessage: t("redirecting.text"),
    autoRedirectDelay: 2000,
    defaultRedirectPath: "/app",
    callbackApiUrl: "/api/federated/callback",
    errorMessageMap: {
      "validation errors": t("errors.validation"),
      client_secret: t("errors.clientSecret"),
      oauth: t("errors.oauth"),
    },
  };

  return <OAuthCallbackPage config={federatedConfig} />;
}
