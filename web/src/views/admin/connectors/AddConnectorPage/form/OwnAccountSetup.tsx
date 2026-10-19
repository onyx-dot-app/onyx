"use client";

import { ValidSources } from "@/lib/connectors/types/source";
import { GoogleOAuthSetup } from "@/views/admin/connectors/AddConnectorPage/form/google/GoogleOAuthSetup";

interface OwnAccountSetupProps {
  source: ValidSources;
}

/**
 * The tab of an auth method that sets the account up on its own (`ownSetup`
 * in the source's credential spec).
 */
export default function OwnAccountSetup({ source }: OwnAccountSetupProps) {
  return source === ValidSources.GoogleDrive ||
    source === ValidSources.Gmail ? (
    <GoogleOAuthSetup source={source} />
  ) : null;
}
