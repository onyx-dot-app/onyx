"use client";

import useSWR, { useSWRConfig } from "swr";
import * as Yup from "yup";

import { LoadingAnimation } from "@/components/Loading";
import { GoogleSitesIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import { TextFormField } from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { ConnectorIndexingStatus, GoogleSitesConfig } from "@/lib/types";
import { Form, Formik } from "formik";
import { useState } from "react";
import { usePopup } from "@/components/admin/connectors/Popup";
import { createConnector, runConnector } from "@/lib/connector";
import { linkCredential } from "@/lib/credential";
import { FileUpload } from "@/components/admin/connectors/FileUpload";
import { SingleUseConnectorsTable } from "@/components/admin/connectors/table/SingleUseConnectorsTable";
import { Spinner } from "@/components/Spinner";
import { AdminPageTitle } from "@/components/admin/Title";
import { Button, Card, Text, Title } from "@tremor/react";

export default function GoogleSites() {
  const { mutate } = useSWRConfig();
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [filesAreUploading, setFilesAreUploading] = useState<boolean>(false);
  const { popup, setPopup } = usePopup();

  const {
    data: connectorIndexingStatuses,
    isLoading: isConnectorIndexingStatusesLoading,
    error: connectorIndexingStatusesError,
  } = useSWR<ConnectorIndexingStatus<any, any>[]>(
    "/api/manage/admin/connector/indexing-status",
    errorHandlingFetcher
  );

  const googleSitesIndexingStatuses: ConnectorIndexingStatus<
    GoogleSitesConfig,
    {}
  >[] =
    connectorIndexingStatuses?.filter(
      (connectorIndexingStatus) =>
        connectorIndexingStatus.connector.source === "google_sites"
    ) ?? [];

  return (
    <>
      {popup}
      {filesAreUploading && <Spinner />}
      <div className="mx-auto container">
        <AdminPageTitle
          icon={<GoogleSitesIcon size={32} />}
          title="Google Sites"
        />

        <Text className="mb-2">
          For an in-depth guide on how to setup this connector, check out{" "}
          <a
            href="https://docs.danswer.dev/connectors/google_sites"
            target="_blank"
            className="text-blue-500"
          >
            the documentation
          </a>
          .
        </Text>

        <div className="mt-4">
          <Title className="mb-2">Upload Files</Title>
          <Card>
            <div className="mx-auto w-full">
              <Formik
                initialValues={{
                  base_url: "",
                }}
                validationSchema={Yup.object().shape({
                  base_url: Yup.string().required("Base URL is required"),
                })}
                onSubmit={async (values, formikHelpers) => {
                  const uploadCreateAndTriggerConnector = async () => {
                    const formData = new FormData();

                    selectedFiles.forEach((file) => {
                      formData.append("files", file);
                    });

                    const response = await fetch(
                      "/api/manage/admin/connector/file/upload",
                      { method: "POST", body: formData }
                    );
                    const responseJson = await response.json();
                    if (!response.ok) {
                      setPopup({
                        message: `Unable to upload files - ${responseJson.detail}`,
                        type: "error",
                      });
                      return;
                    }

                    const filePaths = responseJson.file_paths as string[];
                    const [connectorErrorMsg, connector] =
                      await createConnector<GoogleSitesConfig>({
                        name: `GoogleSitesConnector-${values.base_url}`,
                        source: "google_sites",
                        input_type: "load_state",
                        connector_specific_config: {
                          base_url: values.base_url,
                          zip_path: filePaths[0],
                        },
                        refresh_freq: null,
                        prune_freq: 0,
                        disabled: false,
                      });
                    if (connectorErrorMsg || !connector) {
                      setPopup({
                        message: `Unable to create connector - ${connectorErrorMsg}`,
                        type: "error",
                      });
                      return;
                    }

                    const credentialResponse = await linkCredential(
                      connector.id,
                      0,
                      values.base_url
                    );
                    if (!credentialResponse.ok) {
                      const credentialResponseJson =
                        await credentialResponse.json();
                      setPopup({
                        message: `Unable to link connector to credential - ${credentialResponseJson.detail}`,
                        type: "error",
                      });
                      return;
                    }

                    const runConnectorErrorMsg = await runConnector(
                      connector.id,
                      [0]
                    );
                    if (runConnectorErrorMsg) {
                      setPopup({
                        message: `Unable to run connector - ${runConnectorErrorMsg}`,
                        type: "error",
                      });
                      return;
                    }

                    mutate("/api/manage/admin/connector/indexing-status");
                    setSelectedFiles([]);
                    formikHelpers.resetForm();
                    setPopup({
                      type: "success",
                      message: "Successfully uploaded files!",
                    });
                  };

                  setFilesAreUploading(true);
                  try {
                    await uploadCreateAndTriggerConnector();
                  } catch (e) {
                    console.log("Failed to index filels: ", e);
                  }
                  setFilesAreUploading(false);
                }}
              >
                {({ values, isSubmitting }) => (
                  <Form>
                    <TextFormField
                      name="base_url"
                      label="Base URL:"
                      placeholder={`Base URL of your Google Site e.g. https://sites.google.com/view/your-site`}
                      subtext="This will be used to generate links for each page."
                      autoCompleteDisabled={true}
                    />

                    <p className="mb-1 font-medium">Files:</p>
                    <FileUpload
                      selectedFiles={selectedFiles}
                      setSelectedFiles={setSelectedFiles}
                      message="Upload a zip file containing the HTML of your Google Site"
                    />
                    <div className="flex">
                      <Button
                        className="mt-4 w-64 mx-auto"
                        size="xs"
                        color="green"
                        type="submit"
                        disabled={
                          selectedFiles.length !== 1 ||
                          !values.base_url ||
                          isSubmitting
                        }
                      >
                        Upload!
                      </Button>
                    </div>
                  </Form>
                )}
              </Formik>
            </div>
          </Card>
        </div>

        <h2 className="font-bold mb-2 mt-6 ml-auto mr-auto">
          Existing Google Site Connectors
        </h2>
        {isConnectorIndexingStatusesLoading ? (
          <LoadingAnimation text="Loading" />
        ) : connectorIndexingStatusesError || !connectorIndexingStatuses ? (
          <div>Error loading indexing history</div>
        ) : googleSitesIndexingStatuses.length > 0 ? (
          <SingleUseConnectorsTable<GoogleSitesConfig, {}>
            connectorIndexingStatuses={googleSitesIndexingStatuses}
            specialColumns={[
              {
                header: "Base URL",
                key: "base_url",
                getValue: (ccPairStatus) => {
                  const connectorConfig =
                    ccPairStatus.connector.connector_specific_config;
                  return (
                    <a
                      className="text-blue-500"
                      href={connectorConfig.base_url}
                    >
                      {connectorConfig.base_url}
                    </a>
                  );
                },
              },
            ]}
            onUpdate={() =>
              mutate("/api/manage/admin/connector/indexing-status")
            }
          />
        ) : (
          <p className="text-sm">No indexed Google Sites found</p>
        )}
      </div>
    </>
  );
}
