import { PopupSpec } from "@/components/admin/connectors/Popup";
import { createConnector, runConnector } from "@/lib/connector";
import { linkCredential } from "@/lib/credential";
import { GoogleSitesConfig } from "@/lib/connectors/connectors";
import { ValidSources } from "@/lib/types";

export const submitGoogleSite = async (
  selectedFiles: File[],
  base_url: any,
  setPopup: (popup: PopupSpec) => void,
  refreshFreq: number,
  pruneFreq: number,
  indexingStart: Date,
  access_type: string,
  groups: number[],
  name?: string
) => {
  const uploadCreateAndTriggerConnector = async () => {
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
      return false;
    }

    const filePaths = responseJson.file_paths as string[];
    if (!filePaths || filePaths.length === 0) {
      setPopup({
        message:
          "File upload was successful, but no file path was returned. Cannot create connector.",
        type: "error",
      });
      return false;
    }

    const filePath = filePaths[0];
    if (filePath === undefined) {
      setPopup({
        message:
          "File upload was successful, but file path is undefined. Cannot create connector.",
        type: "error",
      });
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
      setPopup({
        message: `Unable to create connector - ${connectorErrorMsg}`,
        type: "error",
      });
      return false;
    }

    const credentialResponse = await linkCredential(
      connector.id,
      0,
      base_url,
      undefined,
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
      message: "Successfully created Google Site connector!",
    });
    return true;
  };

  try {
    const response = await uploadCreateAndTriggerConnector();
    return response;
  } catch (e) {
    return false;
  }
};
