"use client";

import { redirect } from "next/navigation";
import { useSearchParams } from "next/navigation";
import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { markdown } from "@opal/utils";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { backToLoginOrSignupCopy, welcomeCardCopy } from "@/lib/auth/copies";

const ERROR_CODE_MESSAGES: Record<string, string> = {
  access_denied: "Access was denied by your identity provider.",
  login_required: "You need to log in with your identity provider first.",
  consent_required:
    "Your identity provider requires consent before continuing.",
  interaction_required:
    "Additional interaction with your identity provider is required.",
  invalid_scope: "The requested permissions are not available.",
  server_error:
    "Your identity provider encountered an error. Please try again.",
  temporarily_unavailable:
    "Your identity provider is temporarily unavailable. Please try again later.",
};

const GENERIC_ERROR_DESCRIPTION = [
  "Some possible issues may include:",
  "- Incorrect or expired login credentials",
  "- Temporary authentication system disruption",
  "- Account access restrictions or permissions",
];

function resolveMessage(raw: string | null): string | null {
  if (!raw) return null;
  return ERROR_CODE_MESSAGES[raw] ?? raw;
}

export default function AuthErrorPage() {
  const searchParams = useSearchParams();
  if (!searchParams?.get("error")) redirect("/auth/login");
  const message = resolveMessage(searchParams.get("error"));
  const { appName, logoUrl } = useSettings();

  return (
    <AuthLayouts.Card
      {...welcomeCardCopy(appName)}
      bottomPrompt={backToLoginOrSignupCopy()}
      logoSrc={logoUrl}
    >
      <AuthLayouts.Message
        messageType="warning"
        title="Something went wrong."
        description={markdown(
          ...(message ? [message] : GENERIC_ERROR_DESCRIPTION),
          "",
          NEXT_PUBLIC_CLOUD_ENABLED
            ? "Try again later. [Contact support](mailto:support@onyx.app)."
            : "Try again later. Please reach out to your system administrator or [contact support](mailto:support@onyx.app)."
        )}
      />
    </AuthLayouts.Card>
  );
}
