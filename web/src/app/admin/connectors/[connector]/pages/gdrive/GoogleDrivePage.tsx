"use client";

import React from "react";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { ValidSources } from "@/lib/types";
import { usePublicCredentials } from "@/lib/hooks";
import { DriveAuthSection } from "./Credential";
import { useUser } from "@/providers/UserProvider";
import {
  useGoogleCredentials,
  refreshAllGoogleData,
} from "@/lib/googleConnector";

const GDriveMain = () => {
  const { isAdmin, user } = useUser();

  // Get all public credentials
  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  // Get Google Drive-specific credentials
  const {
    data: googleDriveCredentials,
    isLoading: isGoogleDriveCredentialsLoading,
    error: googleDriveCredentialsError,
  } = useGoogleCredentials(ValidSources.GoogleDrive);

  // Handle refresh of all data
  const handleRefresh = () => {
    refreshCredentials();
    refreshAllGoogleData(ValidSources.GoogleDrive);
  };

  // Loading state
  if (
    (!credentialsData && isCredentialsLoading) ||
    (!googleDriveCredentials && isGoogleDriveCredentialsLoading)
  ) {
    return (
      <div className="mx-auto">
        <LoadingAnimation text="" />
      </div>
    );
  }

  // Error states
  if (credentialsError || !credentialsData) {
    return <ErrorCallout errorTitle="Failed to load credentials." />;
  }

  if (googleDriveCredentialsError || !googleDriveCredentials) {
    return (
      <ErrorCallout errorTitle="Failed to load Google Drive credentials." />
    );
  }

  return (
    <>
      {isAdmin && (
        <>
          <DriveAuthSection
            refreshCredentials={handleRefresh}
            user={user}
            existingOauthCredentials={credentialsData.filter(
              (credential) =>
                credential.source === "google_drive" &&
                (credential.credential_json?.google_app_credential ||
                  credential.credential_json?.google_tokens)
            )}
          />
        </>
      )}
    </>
  );
};

export default GDriveMain;
