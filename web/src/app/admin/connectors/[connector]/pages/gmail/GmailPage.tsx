"use client";

import React from "react";
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
  const { isAdmin, user } = useUser();

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
    return <ErrorCallout errorTitle="Failed to load credentials." />;
  }

  if (gmailCredentialsError || !gmailCredentials) {
    return <ErrorCallout errorTitle="Failed to load Gmail credentials." />;
  }

  return (
    <>
      {isAdmin && (
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
