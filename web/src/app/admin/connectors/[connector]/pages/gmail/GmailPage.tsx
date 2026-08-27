"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { toast } from "@opal/layouts";
import { ValidSources } from "@/lib/types";
import {
  Credential,
  GmailCredentialJson,
  GmailServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import { GmailAuthSection } from "./Credential";
import { usePublicCredentials } from "@/lib/hooks";
import { useUser } from "@/providers/UserProvider";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import {
  useGoogleCredentials,
  refreshAllGoogleData,
} from "@/lib/googleConnector";

interface GmailMainProps {
  buildMode?: boolean;
  onOAuthRedirect?: () => void;
}

export const GmailMain = ({
  buildMode = false,
  onOAuthRedirect,
}: GmailMainProps) => {
  const t = useTranslations("admin.connectorsList");
  const { user } = useUser();
  // See GoogleDrivePage — same gate, same reasoning.
  const { isGlobalHolder } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );

  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  const {
    data: gmailCredentials,
    isLoading: isGmailCredentialsLoading,
    error: gmailCredentialsError,
  } = useGoogleCredentials(ValidSources.Gmail);

  const handleRefresh = () => {
    refreshCredentials();
    refreshAllGoogleData(ValidSources.Gmail);
  };

  if (
    (!credentialsData && isCredentialsLoading) ||
    (!gmailCredentials && isGmailCredentialsLoading)
  ) {
    return (
      <div className="mx-auto">
        <LoadingAnimation text="" />
      </div>
    );
  }

  if (credentialsError || !credentialsData) {
    return <ErrorCallout errorTitle={t("credentialsLoadError.title")} />;
  }

  if (gmailCredentialsError || !gmailCredentials) {
    return <ErrorCallout errorTitle={t("gmail.credentialsLoadError.title")} />;
  }

  return (
    <>
      {isGlobalHolder && (
        <>
          <GmailAuthSection
            refreshCredentials={handleRefresh}
            user={user}
            buildMode={buildMode}
            onOAuthRedirect={onOAuthRedirect}
          />
        </>
      )}
    </>
  );
};
