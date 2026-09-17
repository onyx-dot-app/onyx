"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { ValidSources } from "@/lib/types";
import { usePublicCredentials } from "@/lib/hooks";
import { DriveAuthSection } from "./Credential";
import { useUser } from "@/providers/UserProvider";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import {
  useGoogleCredentials,
  refreshAllGoogleData,
} from "@/lib/googleConnector";

const GDriveMain = () => {
  const t = useTranslations("admin.connectorsList");
  const { user } = useUser();
  // Gated on the global holder, not isAdmin: managing connectors is what this
  // form does, and every endpoint behind it already enforces MANAGE_CONNECTORS.
  const { isGlobalHolder } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );

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
    return <ErrorCallout errorTitle={t("credentialsLoadError.title")} />;
  }

  if (googleDriveCredentialsError || !googleDriveCredentials) {
    return <ErrorCallout errorTitle={t("gdrive.credentialsLoadError.title")} />;
  }

  return (
    <>
      {isGlobalHolder && (
        <>
          <DriveAuthSection refreshCredentials={handleRefresh} user={user} />
        </>
      )}
    </>
  );
};

export default GDriveMain;
