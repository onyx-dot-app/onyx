"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { setupGoogleDriveOAuth } from "@/lib/googleDrive";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { Button, InputSingleUpload, Text } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { parseOauthAppCredentialJson } from "@/lib/credentials/utils";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";

/**
 * Google Drive's OAuth tab: upload the OAuth app JSON, then sign in with
 * Google. The sign-in saves the account itself and returns to the page.
 * Only a global connector manager can do it, as every endpoint behind it
 * enforces.
 */
export function DriveOAuthSetup() {
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

  async function authenticate() {
    if (!oauthAppCredential) return;
    setIsAuthenticating(true);
    try {
      const [authUrl, errorMsg] = await setupGoogleDriveOAuth({
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
      toast.error(t("gdrive.authFailed.toast", { error: String(error) }));
      setIsAuthenticating(false);
    }
  }

  return (
    <Section alignItems="stretch" gap={4}>
      <Text as="p" font="secondary-body" color="text-03">
        {markdown(
          t("gdrive.oauthOption.description", {
            docsUrl: `${DOCS_ADMINS_PATH}/connectors/official/google_drive/overview`,
          })
        )}
      </Text>
      <Text as="p" font="secondary-body" color="text-03">
        {markdown(
          t("gdrive.oauthOption.sharedScopesNote", {
            docsUrl: `${DOCS_ADMINS_PATH}/connectors/official/google_drive/oauth#using-one-credential-for-gmail-and-google-drive`,
          })
        )}
      </Text>
      <InputSingleUpload
        accept="application/json,.json"
        placeholder={t("gdrive.oauthUpload.placeholder")}
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
          {isAuthenticating
            ? t("gdrive.authenticateButton.pendingLabel")
            : t("gdrive.authenticateButton.label")}
        </Button>
      </Section>
    </Section>
  );
}
