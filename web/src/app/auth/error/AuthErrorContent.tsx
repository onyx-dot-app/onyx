"use client";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { Button, Text } from "@opal/components";
import { richNodes } from "@opal/utils";
import { useTranslations } from "next-intl";

import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

// Raw IdP/OAuth error codes that map to a friendlier translated message.
// Any other code is shown to the user as-is.
const KNOWN_ERROR_CODES = [
  "OAUTH_USER_ALREADY_EXISTS",
  "LOGIN_BAD_CREDENTIALS",
  "access_denied",
  "login_required",
  "consent_required",
  "interaction_required",
  "invalid_scope",
  "server_error",
  "temporarily_unavailable",
] as const;

type KnownErrorCode = (typeof KNOWN_ERROR_CODES)[number];

function isKnownErrorCode(value: string): value is KnownErrorCode {
  // SAFETY: the cast only widens the argument for the readonly-array
  // `includes` signature; membership is still checked at runtime.
  return KNOWN_ERROR_CODES.includes(value as KnownErrorCode);
}

function resolveMessage(
  raw: string | null,
  messages: Record<KnownErrorCode, string>
): string | null {
  if (!raw) return null;
  return isKnownErrorCode(raw) ? messages[raw] : raw;
}

interface AuthErrorContentProps {
  message: string | null;
}

function AuthErrorContent({ message: rawMessage }: AuthErrorContentProps) {
  const t = useTranslations("auth");
  const errorCodeMessages = {
    OAUTH_USER_ALREADY_EXISTS: t("error.code.oauthUserAlreadyExists"),
    LOGIN_BAD_CREDENTIALS: t("error.code.loginBadCredentials"),
    access_denied: t("error.code.accessDenied"),
    login_required: t("error.code.loginRequired"),
    consent_required: t("error.code.consentRequired"),
    interaction_required: t("error.code.interactionRequired"),
    invalid_scope: t("error.code.invalidScope"),
    server_error: t("error.code.serverError"),
    temporarily_unavailable: t("error.code.temporarilyUnavailable"),
  } satisfies Record<KnownErrorCode, string>;
  const message = resolveMessage(rawMessage, errorCodeMessages);
  return (
    <AuthFlowContainer>
      <div className="flex flex-col items-center gap-4">
        <Text font="heading-h2" color="text-05">
          {t("error.heading.title")}
        </Text>
        <Text font="main-content-body" color="text-03">
          {t("error.heading.description")}
        </Text>
        {/* TODO: Error card component */}
        <div className="w-full rounded-12 border border-status-error-05 bg-status-error-00 p-4">
          {message ? (
            <Text font="main-content-body" color="status-error-05">
              {message}
            </Text>
          ) : (
            <div className="flex flex-col gap-2 px-4">
              <Text font="main-content-emphasis" color="status-error-05">
                {t("error.possibleIssues.title")}
              </Text>
              <Text as="li" font="main-content-body" color="status-error-05">
                {t("error.credentialsIssue.description")}
              </Text>
              <Text as="li" font="main-content-body" color="status-error-05">
                {t("error.systemDisruptionIssue.description")}
              </Text>
              <Text as="li" font="main-content-body" color="status-error-05">
                {t("error.accessRestrictionIssue.description")}
              </Text>
            </div>
          )}
        </div>

        <Button href="/auth/login" width="full">
          {t("error.returnToLoginButton.label")}
        </Button>

        <Text font="main-content-body" color="text-04">
          {NEXT_PUBLIC_CLOUD_ENABLED
            ? richNodes(
                t.rich("error.cloudSupportPrompt.text", {
                  link: (chunks) => (
                    <a
                      href="mailto:support@onyx.app"
                      className="text-action-selection-05"
                    >
                      {chunks}
                    </a>
                  ),
                })
              )
            : t("error.selfHostedSupportPrompt.text")}
        </Text>
      </div>
    </AuthFlowContainer>
  );
}

export default AuthErrorContent;
