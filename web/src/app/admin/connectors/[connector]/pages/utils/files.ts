import { PopupSpec } from "@/components/admin/connectors/Popup";
import { createConnector, runConnector } from "@/lib/connector";
import { createCredential, linkCredential } from "@/lib/credential";
import { FileConfig } from "@/lib/connectors/connectors";
import { AccessType, ValidSources } from "@/lib/types";

export const submitFiles = async (
  selectedFiles: File[],
  setPopup: (popup: PopupSpec) => void,
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
  const responseJson = await response.json();
  if (!response.ok) {
    setPopup({
      message: `Unable to upload files - ${responseJson.detail}`,
      type: "error",
    });
    return;
  }

  const filePaths = responseJson.file_paths as string[];
  const fileNames = responseJson.file_names as string[];
  const zipMetadata = responseJson.zip_metadata as Record<string, any>;

  const [connectorErrorMsg, connector] = await createConnector<FileConfig>({
    name: "FileConnector-" + Date.now(),
    source: ValidSources.File,
    input_type: "load_state",
    connector_specific_config: {
      file_locations: filePaths,
      file_names: fileNames,
      zip_metadata: zipMetadata,
    },
    refresh_freq: null,
    prune_freq: null,
    indexing_start: null,
    access_type: access_type,
    groups: groups,
  });
  if (connectorErrorMsg || !connector) {
    setPopup({
      message: `Unable to create connector - ${connectorErrorMsg}`,
      type: "error",
    });
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
    setPopup({
      message: `Error creating credential for CC Pair - ${errorMsg}`,
      type: "error",
    });
    return;
    false;
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
    const credentialResponseJson = await credentialResponse.json();
    setPopup({
      message: `Unable to link connector to credential - ${credentialResponseJson.detail}`,
      type: "error",
    });
    return false;
  }

  const runConnectorErrorMsg = await runConnector(connector.id, [0]);
  if (runConnectorErrorMsg) {
    setPopup({
      message: `Unable to run connector - ${runConnectorErrorMsg}`,
      type: "error",
    });
    return false;
  }

  setPopup({
    type: "success",
    message: "Successfully uploaded files!",
  });
  return true;
};
