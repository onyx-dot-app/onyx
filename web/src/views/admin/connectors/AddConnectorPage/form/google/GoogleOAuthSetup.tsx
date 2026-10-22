"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { setupGmailOAuth } from "@/lib/gmail";
import { setupGoogleDriveOAuth } from "@/lib/googleDrive";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { Button, InputSingleUpload, Text } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { parseOauthAppCredentialJson } from "@/lib/credentials/utils";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { ValidSources } from "@/lib/connectors/types/source";

interface GoogleOAuthSetupProps {
  source: ValidSources.GoogleDrive | ValidSources.Gmail;
}

/**
 * The OAuth tab of a Google account (Gmail, Google Drive): upload the OAuth
 * app JSON, then sign in with Google. The sign-in saves the account itself
 * and returns to the page. Only a global connector manager can do it, as
 * every endpoint behind it enforces.
 */
export function GoogleOAuthSetup({ source }: GoogleOAuthSetupProps) {
  const t = useTranslations("admin.connectorsList");
  const router = useRouter();
  const { isGlobalHolder } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [oauthAppCredential, setOauthAppCredential] = useState<Record<
    string,
    unknown
  > | null>(null);

  if (!isGlobalHolder) return null;

  const isGmail = source === ValidSources.Gmail;
  const copy = isGmail
    ? {
        description: t("gmail.oauthOption.description", {
          docsUrl: `${DOCS_ADMINS_PATH}/connectors/official/gmail/overview`,
        }),
        sharedScopesNote: t("gmail.oauthOption.sharedScopesNote", {
          docsUrl: `${DOCS_ADMINS_PATH}/connectors/official/google_drive/oauth#using-one-credential-for-gmail-and-google-drive`,
        }),
        uploadPlaceholder: t("gmail.oauthUpload.placeholder"),
        authenticate: t("gmail.authenticateButton.label"),
        authenticating: t("gmail.authenticateButton.pendingLabel"),
        authFailed: (error: string) => t("gmail.authFailed.toast", { error }),
      }
    : {
        description: t("gdrive.oauthOption.description", {
          docsUrl: `${DOCS_ADMINS_PATH}/connectors/official/google_drive/overview`,
        }),
        sharedScopesNote: t("gdrive.oauthOption.sharedScopesNote", {
          docsUrl: `${DOCS_ADMINS_PATH}/connectors/official/google_drive/oauth#using-one-credential-for-gmail-and-google-drive`,
        }),
        uploadPlaceholder: t("gdrive.oauthUpload.placeholder"),
        authenticate: t("gdrive.authenticateButton.label"),
        authenticating: t("gdrive.authenticateButton.pendingLabel"),
        authFailed: (error: string) => t("gdrive.authFailed.toast", { error }),
      };

  async function authenticate() {
    if (!oauthAppCredential) return;
    setIsAuthenticating(true);
    try {
      const [authUrl, errorMsg] = isGmail
        ? await setupGmailOAuth({
            isAdmin: true,
            appCredential: oauthAppCredential,
          })
        : await setupGoogleDriveOAuth({
            isAdmin: true,
            name: "OAuth (uploaded)",
            appCredential: oauthAppCredential,
          });
      if (authUrl) {
        router.push(authUrl as Route);
      } else {
        toast.error(errorMsg);
        setIsAuthenticating(false);
      }
    } catch (error) {
      toast.error(copy.authFailed(String(error)));
      setIsAuthenticating(false);
    }
  }

  return (
    <Section alignItems="stretch" gap={4}>
      <Text as="p" font="secondary-body" color="text-03">
        {markdown(copy.description)}
      </Text>
      <Text as="p" font="secondary-body" color="text-03">
        {markdown(copy.sharedScopesNote)}
      </Text>
      <InputSingleUpload
        accept="application/json,.json"
        placeholder={copy.uploadPlaceholder}
        setValue={(value) => {
          setOauthAppCredential(
            value ? parseOauthAppCredentialJson(value) : null
          );
        }}
      />
      <Section flexDirection="row" justifyContent="end">
        <Button
          disabled={!oauthAppCredential || isAuthenticating}
          onClick={() => void authenticate()}
        >
          {isAuthenticating ? copy.authenticating : copy.authenticate}
        </Button>
      </Section>
    </Section>
  );
}
