"use client";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useTranslations } from "next-intl";

// Maps raw IdP/OAuth error codes to user-friendly messages.
// If the message is a known code, we replace it; otherwise show it as-is.
const ERROR_CODE_MESSAGE_KEYS: Record<string, string> = {
  access_denied: "accessDenied",
  login_required: "loginRequired",
  consent_required: "consentRequired",
  interaction_required: "interactionRequired",
  invalid_scope: "invalidScope",
  server_error: "serverError",
  temporarily_unavailable: "temporarilyUnavailable",
};

function resolveMessage(
  raw: string | null,
  t: (key: string) => string
): string | null {
  if (!raw) return null;
  const messageKey = ERROR_CODE_MESSAGE_KEYS[raw];
  return messageKey ? t(messageKey) : raw;
}

interface AuthErrorContentProps {
  message: string | null;
}

function AuthErrorContent({ message: rawMessage }: AuthErrorContentProps) {
  const t = useTranslations("auth.error");
  const message = resolveMessage(rawMessage, t);
  return (
    <AuthFlowContainer>
      <div className="flex flex-col items-center gap-4">
        <Text headingH2 text05>
          {t("title")}
        </Text>
        <Text mainContentBody text03>
          {t("description")}
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
                {t("possibleIssues")}
              </Text>
              <Text as="li" mainContentBody className="text-status-error-05">
                {t("incorrectCredentials")}
              </Text>
              <Text as="li" mainContentBody className="text-status-error-05">
                {t("temporaryDisruption")}
              </Text>
              <Text as="li" mainContentBody className="text-status-error-05">
                {t("accessRestrictions")}
              </Text>
            </div>
          )}
        </div>

        <Button href="/auth/login" width="full">
          {t("returnToLogin")}
        </Button>

        <Text mainContentBody text04>
          {NEXT_PUBLIC_CLOUD_ENABLED ? (
            <>
              {t("contactSupportCloud")}{" "}
              <a href="mailto:support@onyx.app" className="text-action-link-05">
                support@onyx.app
              </a>
            </>
          ) : (
            t("contactSupportSelfHosted")
          )}
        </Text>
      </div>
    </AuthFlowContainer>
  );
}

export default AuthErrorContent;
