"use client";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

// Maps raw IdP/OAuth error codes to user-friendly messages.
// If the message is a known code, we replace it; otherwise show it as-is.
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

interface AuthErrorContentProps {
  message: string | null;
}

function AuthErrorContent({ message: rawMessage }: AuthErrorContentProps) {
  const message = resolveMessage(rawMessage);
  return (
    <AuthFlowContainer>
      <div className="flex flex-col items-center gap-4">
        <Text headingH2 text05>
          Authentication Error
        </Text>
        <Text mainContentBody text03>
          There was a problem with your login attempt.
        </Text>
        {/* TODO: Error card component */}
        <div className="w-full rounded-12 border border-status-error-05 bg-status-error-00 p-4">
          {message ? (
            <Text mainContentBody className="text-status-error-05">
              {message}
            </Text>
          ) : (
            <div className="flex flex-col gap-2 px-4">
              <Text mainContentEmphasis className="text-status-error-05">
                Possible Issues:
              </Text>
              <Text as="li" mainContentBody className="text-status-error-05">
                Incorrect or expired login credentials
              </Text>
              <Text as="li" mainContentBody className="text-status-error-05">
                Temporary authentication system disruption
              </Text>
              <Text as="li" mainContentBody className="text-status-error-05">
                Account access restrictions or permissions
              </Text>
            </div>
          )}
        </div>

        <Button href="/auth/login" width="full">
          Return to Login Page
        </Button>

        <Text mainContentBody text04>
          {NEXT_PUBLIC_CLOUD_ENABLED ? (
            <>
              If you continue to experience problems, please reach out to the
              Onyx team at{" "}
              <a href="mailto:support@onyx.app" className="text-action-link-05">
                support@onyx.app
              </a>
            </>
          ) : (
            "If you continue to experience problems, please reach out to your system administrator for assistance."
          )}
        </Text>
      </div>
    </AuthFlowContainer>
  );
}

export default AuthErrorContent;
