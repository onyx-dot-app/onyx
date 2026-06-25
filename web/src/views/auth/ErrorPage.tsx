"use client";

import { useSearchParams } from "next/navigation";
import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { Text, Button } from "@opal/components";
import { markdown } from "@opal/utils";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

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

function resolveMessage(raw: string | null): string | null {
  if (!raw) return null;
  return ERROR_CODE_MESSAGES[raw] ?? raw;
}

export default function ErrorPage() {
  const searchParams = useSearchParams();
  const message = resolveMessage(searchParams?.get("error") ?? null);
  const { logoUrl } = useSettings();

  return (
    <AuthLayouts.Card
      title="Authentication Error"
      description="There was a problem with your login attempt."
      logoSrc={logoUrl}
    >
      <div className="flex flex-col gap-4">
        {/* TODO: Error card component */}
        <div className="w-full rounded-12 border border-status-error-05 bg-status-error-00 p-4">
          {message ? (
            <div className="text-status-error-05">
              <Text font="main-content-body">{message}</Text>
            </div>
          ) : (
            <div className="flex flex-col gap-2 px-4 text-status-error-05">
              <Text font="main-content-emphasis">Possible Issues:</Text>
              <Text as="li" font="main-content-body">
                Incorrect or expired login credentials
              </Text>
              <Text as="li" font="main-content-body">
                Temporary authentication system disruption
              </Text>
              <Text as="li" font="main-content-body">
                Account access restrictions or permissions
              </Text>
            </div>
          )}
        </div>

        <Button href="/auth/login" width="full">
          Return to Login Page
        </Button>

        <Text font="main-content-body" color="text-04">
          {NEXT_PUBLIC_CLOUD_ENABLED
            ? markdown(
                "If you continue to experience problems, please reach out to the Onyx team at [support@onyx.app](mailto:support@onyx.app)"
              )
            : "If you continue to experience problems, please reach out to your system administrator for assistance."}
        </Text>
      </div>
    </AuthLayouts.Card>
  );
}
