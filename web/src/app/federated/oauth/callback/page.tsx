"use client";

import OAuthCallbackPage from "@/components/oauth/OAuthCallbackPage";
import { getSourceDisplayName } from "@/lib/sources";

export default function FederatedOAuthCallbackPage() {
  const federatedConfig = {
    processingMessage: "Processing...",
    processingDetails: "Please wait while we complete the setup.",
    successMessage: "Success!",
    successDetailsTemplate:
      "Your {serviceName} authorization completed successfully. You can now use this connector for search.",
    errorMessage: "Something Went Wrong",
    backButtonText: "Back to Chat",
    redirectingMessage: "Redirecting to chat in 2 seconds...",
    autoRedirectDelay: 2000,
    defaultRedirectPath: "/chat",
    callbackApiUrl: "/api/federated/callback",
    errorMessageMap: {
      "validation errors":
        "Configuration error - please check your connector settings",
      client_secret: "Authentication credentials are missing or invalid",
      oauth: "OAuth authorization failed",
    },
  };

  return <OAuthCallbackPage config={federatedConfig} />;
}
