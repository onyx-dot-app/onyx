"use client";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { Button, Text } from "@opal/components";
import { useNavigation } from "@opal/navigation";
import { cn, richNodes } from "@opal/utils";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { CONTACT_SALES_URL, NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { loginPath, signupPath } from "@/lib/auth/paths";
import { isStaleSsoStateError } from "@/lib/auth/utils";

// Raw IdP/OAuth error codes that map to a friendlier translated message.
// Stale-state codes get their own message. Any other code is shown as-is.
// PLAYGROUND_* codes are not errors: the playground refused a sign-up and
// this page tells the person what to do next.
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
  "PLAYGROUND_EMAIL_USED",
  "PLAYGROUND_FREE_MAIL",
  "PLAYGROUND_LIMIT_REACHED",
  "PLAYGROUND_ACTIVE_TENANT",
  "PLAYGROUND_CHECK_FAILED",
] as const;

// A team from the domain has a running trial: join it, or start a new one.
const TEAM_CHOICE_CODE = "PLAYGROUND_ACTIVE_TENANT";

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
  const navigation = useNavigation();
  // "Join your team" swaps the question for its next step.
  const [joinChosen, setJoinChosen] = useState(false);
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
    PLAYGROUND_EMAIL_USED: t("error.code.playgroundEmailUsed"),
    PLAYGROUND_FREE_MAIL: t("error.code.playgroundFreeMail"),
    PLAYGROUND_LIMIT_REACHED: t("error.code.playgroundLimitReached"),
    PLAYGROUND_ACTIVE_TENANT: t("error.code.playgroundActiveTenant"),
    PLAYGROUND_CHECK_FAILED: t("error.code.playgroundCheckFailed"),
  } satisfies Record<KnownErrorCode, string>;
  const isPlayground = rawMessage?.startsWith("PLAYGROUND_") ?? false;
  const isTeamChoice = rawMessage === TEAM_CHOICE_CODE && !joinChosen;
  // Every other playground page points to sales.
  const isContactSales = isPlayground && rawMessage !== TEAM_CHOICE_CODE;

  let message: string | null;
  if (isStaleSsoStateError(rawMessage)) {
    message = t("error.code.staleSignIn");
  } else if (rawMessage === TEAM_CHOICE_CODE && joinChosen) {
    message = t("error.code.playgroundAskAdmin");
  } else {
    message = resolveMessage(rawMessage, errorCodeMessages);
  }

  return (
    <AuthFlowContainer>
      <div className="flex flex-col items-center gap-4">
        <Text font="heading-headline" color="text-05">
          {isPlayground
            ? t("error.playgroundHeading.title")
            : t("error.heading.title")}
        </Text>
        {!isPlayground && (
          <Text font="main-content-body" color="text-03">
            {t("error.heading.description")}
          </Text>
        )}
        {/* TODO: Error card component */}
        <div
          className={cn(
            "w-full rounded-12 border p-4",
            isPlayground
              ? "border-border-01 bg-background-tint-01"
              : "border-status-error-05 bg-status-error-00"
          )}
        >
          {message ? (
            <Text
              font="main-content-body"
              color={isPlayground ? "text-05" : "status-error-05"}
            >
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

        {isTeamChoice ? (
          <>
            <Button
              {...navigation.linkTo(signupPath({ startNewTeam: true }))}
              width="full"
            >
              {t("error.startNewTeamButton.label")}
            </Button>
            <Button
              prominence="secondary"
              width="full"
              onClick={() => setJoinChosen(true)}
            >
              {t("error.joinTeamButton.label")}
            </Button>
          </>
        ) : isContactSales ? (
          <>
            <Button
              href={CONTACT_SALES_URL}
              target="_blank"
              rel="noopener noreferrer"
              width="full"
            >
              {t("error.contactSalesButton.label")}
            </Button>
            <Button
              prominence="secondary"
              {...navigation.linkTo(loginPath({ autoRedirectToSso: false }))}
              width="full"
            >
              {t("error.returnToLoginButton.label")}
            </Button>
          </>
        ) : (
          /* Held on the button: the IdP just failed, so no bounce back to it. */
          <Button
            {...navigation.linkTo(loginPath({ autoRedirectToSso: false }))}
            width="full"
          >
            {t("error.returnToLoginButton.label")}
          </Button>
        )}

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
