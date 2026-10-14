"use client";

import { ValidSources } from "@/lib/connectors/types/source";
import { DriveOAuthSetup } from "@/views/admin/connectors/AddConnectorPage/form/gdrive/Credential";

interface OwnAccountSetupProps {
  source: ValidSources;
}

/**
 * The tab of an auth method that sets the account up on its own (`ownSetup`
 * in the source's credential spec).
 */
export default function OwnAccountSetup({ source }: OwnAccountSetupProps) {
  return source === ValidSources.GoogleDrive ? <DriveOAuthSetup /> : null;
}
