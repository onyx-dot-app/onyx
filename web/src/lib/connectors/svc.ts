import { mutate } from "swr";
import { toast } from "@opal/layouts";
import { createConnector, runConnector } from "@/lib/connector";
import { createCredential, linkCredential } from "@/lib/credential";
import { parseErrorDetail, type ErrorResponseBody } from "@/lib/fetcher";
import type { FileUploadResponse } from "@/lib/fileConnector";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import type { FileConfig, GoogleSitesConfig } from "@/lib/connectors/types";
import { AccessType, ValidSources } from "@/lib/types";

// ---------------------------------------------------------------------------
// Indexing
// ---------------------------------------------------------------------------

export async function triggerIndexing(
  fromBeginning: boolean,
  connectorId: number,
  credentialId: number,
  ccPairId: number
): Promise<{ success: boolean; message: string }> {
  const errorMsg = await runConnector(
    connectorId,
    [credentialId],
    fromBeginning
  );

  mutate(buildCCPairInfoUrl(ccPairId));

  if (errorMsg) {
    return {
      success: false,
      message: errorMsg,
    };
  } else {
    return {
      success: true,
      message: "Triggered connector run",
    };
  }
}

// ---------------------------------------------------------------------------
// File and Google Sites connectors: upload, create, link, run
// ---------------------------------------------------------------------------

export const submitFiles = async (
  selectedFiles: File[],
  name: string,
  access_type: string,
  groups?: number[]
) => {
  const formData = new FormData();

  selectedFiles.forEach((file) => {
    formData.append("files", file);
  });

  const response = await fetch("/api/manage/admin/connector/file/upload", {
    method: "POST",
    body: formData,
  });
  const responseJson: Partial<FileUploadResponse> & ErrorResponseBody =
    await response.json();
  if (!response.ok) {
    toast.error(`Unable to upload files - ${responseJson.detail}`);
    return;
  }

  const filePaths = responseJson.file_paths as string[];
  const fileNames = responseJson.file_names as string[];
  const zipMetadataFileId = responseJson.zip_metadata_file_id as string | null;

  const [connectorErrorMsg, connector] = await createConnector<FileConfig>({
    name: "FileConnector-" + Date.now(),
    source: ValidSources.File,
    input_type: "load_state",
    connector_specific_config: {
      file_locations: filePaths,
      file_names: fileNames,
      zip_metadata_file_id: zipMetadataFileId,
    },
    refresh_freq: null,
    prune_freq: null,
    indexing_start: null,
    access_type: access_type,
    groups: groups,
  });
  if (connectorErrorMsg || !connector) {
    toast.error(`Unable to create connector - ${connectorErrorMsg}`);
    return;
  }

  // Since there is no "real" credential associated with a file connector
  // we create a dummy one here so that we can associate the CC Pair with a
  // user. This is needed since the user for a CC Pair is found via the credential
  // associated with it.
  const createCredentialResponse = await createCredential({
    credential_json: {},
    admin_public: true,
    source: ValidSources.File,
    curator_public: true,
    groups: groups,
    name,
  });
  if (!createCredentialResponse.ok) {
    const errorMsg = await createCredentialResponse.text();
    toast.error(`Error creating credential for CC Pair - ${errorMsg}`);
    return false;
  }
  const credentialId = (await createCredentialResponse.json()).id;

  const credentialResponse = await linkCredential(
    connector.id,
    credentialId,
    name,
    access_type as AccessType,
    groups
  );
  if (!credentialResponse.ok) {
    const credentialResponseJson: ErrorResponseBody =
      await credentialResponse.json();
    toast.error(
      `Unable to link connector to credential - ${credentialResponseJson.detail}`
    );
    return false;
  }

  const runConnectorErrorMsg = await runConnector(connector.id, [0]);
  if (runConnectorErrorMsg) {
    toast.error(`Unable to run connector - ${runConnectorErrorMsg}`);
    return false;
  }

  toast.success("Successfully uploaded files!");
  return true;
};

export const submitGoogleSite = async (
  selectedFiles: File[],
  base_url: string,
  refreshFreq: number,
  pruneFreq: number,
  indexingStart: Date,
  access_type: AccessType,
  groups: number[],
  name?: string
) => {
  const uploadCreateAndTriggerConnector = async () => {
    const formData = new FormData();

    selectedFiles.forEach((file) => {
      formData.append("files", file);
    });

    const response = await fetch(
      "/api/manage/admin/connector/file/upload?unzip=false",
      {
        method: "POST",
        body: formData,
      }
    );
    const responseJson: Partial<FileUploadResponse> & ErrorResponseBody =
      await response.json();
    if (!response.ok) {
      toast.error(`Unable to upload files - ${responseJson.detail}`);
      return false;
    }

    const filePaths = responseJson.file_paths;
    if (!filePaths || filePaths.length === 0) {
      toast.error(
        "File upload was successful, but no file path was returned. Cannot create connector."
      );
      return false;
    }

    const filePath = filePaths[0];
    if (filePath === undefined) {
      toast.error(
        "File upload was successful, but file path is undefined. Cannot create connector."
      );
      return false;
    }

    const [connectorErrorMsg, connector] =
      await createConnector<GoogleSitesConfig>({
        name: name ? name : `GoogleSitesConnector-${base_url}`,
        source: ValidSources.GoogleSites,
        input_type: "load_state",
        connector_specific_config: {
          base_url: base_url,
          zip_path: filePath,
        },
        access_type: access_type,
        refresh_freq: refreshFreq,
        prune_freq: pruneFreq,
        indexing_start: indexingStart,
      });
    if (connectorErrorMsg || !connector) {
      toast.error(`Unable to create connector - ${connectorErrorMsg}`);
      return false;
    }

    const credentialResponse = await linkCredential(
      connector.id,
      0,
      base_url,
      access_type,
      groups
    );
    if (!credentialResponse.ok) {
      const credentialResponseJson: ErrorResponseBody =
        await credentialResponse.json();
      toast.error(
        `Unable to link connector to credential - ${credentialResponseJson.detail}`
      );
      return false;
    }

    const runConnectorErrorMsg = await runConnector(connector.id, [0]);
    if (runConnectorErrorMsg) {
      toast.error(`Unable to run connector - ${runConnectorErrorMsg}`);
      return false;
    }
    toast.success("Successfully created Google Site connector!");
    return true;
  };

  try {
    const response = await uploadCreateAndTriggerConnector();
    return response;
  } catch (e) {
    return false;
  }
};

// ---------------------------------------------------------------------------
// OAuth
// ---------------------------------------------------------------------------

const OAUTH_REDIRECT_ERROR = "Unable to start OAuth";
const OAUTH_REDIRECT_LOG_ERROR = "Failed to fetch OAuth redirect URL";

interface OAuthRedirectResponse {
  redirect_url: string;
}

export async function getConnectorOauthRedirectUrl(
  connector: ValidSources,
  additional_kwargs: Record<string, string>
): Promise<string> {
  try {
    const queryParams = new URLSearchParams({
      desired_return_url: `${window.location.pathname}${window.location.search}${window.location.hash}`,
      ...additional_kwargs,
    });
    const response = await fetch(
      `/api/connector/oauth/authorize/${connector}?${queryParams.toString()}`
    );

    if (!response.ok) {
      throw new Error(await parseErrorDetail(response, OAUTH_REDIRECT_ERROR));
    }

    const data: OAuthRedirectResponse = await response.json();
    return data.redirect_url;
  } catch (error) {
    console.error(`${OAUTH_REDIRECT_LOG_ERROR} for ${connector}:`, error);
    throw error;
  }
}
