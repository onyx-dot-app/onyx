"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { HealthCheckBanner } from "@/components/health/healthcheck";

import { Card, Title } from "@tremor/react";
import { AdminPageTitle } from "@/components/admin/Title";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useFormContext } from "@/components/context/FormContext";
import { getSourceDisplayName } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
import { useState } from "react";
import { submitConnector } from "@/components/admin/connectors/ConnectorForm";
import { deleteCredential, linkCredential } from "@/lib/credential";
import { submitFiles } from "./pages/utils/files";
import { submitGoogleSite } from "./pages/utils/google_site";
import AdvancedFormPage from "./pages/Advanced";
import DynamicConnectionForm from "./pages/DynamicConnectorCreationForm";
import CreateCredential from "@/components/credentials/actions/CreateCredential";
import ModifyCredential from "@/components/credentials/actions/ModifyCredential";
import { ConfigurableSources, ValidSources } from "@/lib/types";
import { Credential, credentialTemplates } from "@/lib/connectors/credentials";
import {
  ConnectionConfiguration,
  connectorConfigs,
  createConnectorInitialValues,
  createConnectorValidationSchema,
} from "@/lib/connectors/connectors";
import { Modal } from "@/components/Modal";
import GDriveMain from "./pages/gdrive/GoogleDrivePage";
import { GmailMain } from "./pages/gmail/GmailPage";
import {
  useGmailCredentials,
  useGoogleDriveCredentials,
} from "./pages/utils/hooks";
import { Formik } from "formik";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import NavigationRow from "./NavigationRow";

export interface AdvancedConfig {
  refreshFreq: number;
  pruneFreq: number;
  indexingStart: string;
}

export default function AddConnector({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  // State for managing credentials and files
  const [currentCredential, setCurrentCredential] =
    useState<Credential<any> | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [createConnectorToggle, setCreateConnectorToggle] = useState(false);

  // Fetch credentials data
  const { data: credentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(connector),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );

  const { data: editableCredentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(connector, true),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );

  // Get credential template and configuration
  const credentialTemplate = credentialTemplates[connector];
  const configuration: ConnectionConfiguration = connectorConfigs[connector];

  // Form context and popup management
  const { setFormStep, setAlowCreate, formStep, nextFormStep, prevFormStep } =
    useFormContext();
  const { popup, setPopup } = usePopup();

  // Hooks for Google Drive and Gmail credentials
  const { liveGDriveCredential } = useGoogleDriveCredentials();
  const { liveGmailCredential } = useGmailCredentials();

  // Check if credential is activated
  const credentialActivated =
    (connector === "google_drive" && liveGDriveCredential) ||
    (connector === "gmail" && liveGmailCredential) ||
    currentCredential;

  // Check if there are no credentials
  const noCredentials = credentialTemplate == null;

  if (noCredentials && 1 != formStep) {
    setFormStep(Math.max(1, formStep));
  }

  if (!noCredentials && !credentialActivated && formStep != 0) {
    setFormStep(Math.min(formStep, 0));
  }

  const convertStringToDateTime = (indexingStart: string | null) => {
    return indexingStart ? new Date(indexingStart) : null;
  };

  const displayName = getSourceDisplayName(connector) || connector;
  if (!credentials || !editableCredentials) {
    return <></>;
  }

  // Credential handler functions
  const refresh = () => {
    mutate(buildSimilarCredentialInfoURL(connector));
  };

  const onDeleteCredential = async (credential: Credential<any | null>) => {
    const response = await deleteCredential(credential.id, true);
    if (response.ok) {
      setPopup({
        message: "Credential deleted successfully!",
        type: "success",
      });
    } else {
      const errorData = await response.json();
      setPopup({
        message: errorData.message,
        type: "error",
      });
    }
  };

  const onSwap = async (selectedCredential: Credential<any>) => {
    setCurrentCredential(selectedCredential);
    setAlowCreate(true);
    setPopup({
      message: "Swapped credential successfully!",
      type: "success",
    });
    refresh();
  };

  const onSuccess = () => {
    setPopup({
      message: "Connector created! Redirecting to connector home page",
      type: "success",
    });
    setTimeout(() => {
      window.open("/admin/indexing/status", "_self");
    }, 1000);
  };

  return (
    <Formik
      initialValues={createConnectorInitialValues(connector)}
      validationSchema={createConnectorValidationSchema(connector)}
      onSubmit={async (values) => {
        console.log(" Iam submiing the connector");
        const {
          name,
          groups,
          is_public: isPublic,
          pruneFreq,
          indexingStart,
          refreshFreq,
          ...connector_specific_config
        } = values;

        // Apply transforms from connectors.ts configuration
        const transformedConnectorSpecificConfig = Object.entries(
          connector_specific_config
        ).reduce(
          (acc, [key, value]) => {
            const matchingConfigValue = configuration.values.find(
              (configValue) => configValue.name === key
            );
            if (
              matchingConfigValue &&
              "transform" in matchingConfigValue &&
              matchingConfigValue.transform
            ) {
              acc[key] = matchingConfigValue.transform(value as string[]);
            } else {
              acc[key] = value;
            }
            return acc;
          },
          {} as Record<string, any>
        );

        // Apply advanced configuration-specific transforms.
        const advancedConfiguration: any = {
          pruneFreq: pruneFreq * 60 * 60 * 24,
          indexingStart: convertStringToDateTime(indexingStart),
          refreshFreq: refreshFreq * 60,
        };

        // Google sites-specific handling
        if (connector == "google_sites") {
          const response = await submitGoogleSite(
            selectedFiles,
            values?.base_url,
            setPopup,
            advancedConfiguration.refreshFreq,
            advancedConfiguration.pruneFreq,
            advancedConfiguration.indexingStart,
            name
          );
          if (response) {
            onSuccess();
          }
          return;
        }

        // File-specific handling
        if (connector == "file" && selectedFiles.length > 0) {
          const response = await submitFiles(
            selectedFiles,
            setPopup,
            setSelectedFiles,
            name,
            isPublic,
            groups
          );
          if (response) {
            onSuccess();
          }
          return;
        }

        const { message, isSuccess, response } = await submitConnector<any>(
          {
            connector_specific_config: transformedConnectorSpecificConfig,
            input_type: connector == "web" ? "load_state" : "poll", // single case
            name: name,
            source: connector,
            refresh_freq: advancedConfiguration.refreshFreq || null,
            prune_freq: advancedConfiguration.pruneFreq || null,
            indexing_start: advancedConfiguration.indexingStart || null,
            is_public: isPublic,
            groups: groups,
          },
          undefined,
          credentialActivated ? false : true,
          isPublic
        );
        // If no credential
        if (!credentialActivated) {
          if (isSuccess) {
            onSuccess();
          } else {
            setPopup({ message: message, type: "error" });
          }
        }

        // Without credential
        if (credentialActivated && isSuccess && response) {
          const credential =
            currentCredential || liveGDriveCredential || liveGmailCredential;
          const linkCredentialResponse = await linkCredential(
            response.id,
            credential?.id!,
            name,
            isPublic,
            groups
          );
          if (linkCredentialResponse.ok) {
            onSuccess();
          } else {
            const errorData = await linkCredentialResponse.json();
            setPopup({
              message: errorData.message,
              type: "error",
            });
          }
        } else if (isSuccess) {
          onSuccess();
        } else {
          setPopup({ message: message, type: "error" });
        }
        return;
      }}
    >
      {(formikProps) => {
        return (
          <div className="mx-auto mb-8 w-full">
            {popup}

            <div className="mb-4">
              <HealthCheckBanner />
            </div>

            <AdminPageTitle
              includeDivider={false}
              icon={<SourceIcon iconSize={32} sourceType={connector} />}
              title={displayName}
            />

            {formStep == 0 && (
              <Card>
                <Title className="mb-2 text-lg">Select a credential</Title>

                {connector == "google_drive" ? (
                  <GDriveMain />
                ) : connector == "gmail" ? (
                  <GmailMain />
                ) : (
                  <>
                    <ModifyCredential
                      showIfEmpty
                      source={connector}
                      defaultedCredential={currentCredential!}
                      credentials={credentials}
                      editableCredentials={editableCredentials}
                      onDeleteCredential={onDeleteCredential}
                      onSwitch={onSwap}
                    />
                    {!createConnectorToggle && (
                      <button
                        className="mt-6 text-sm bg-background-900 px-2 py-1.5 flex text-text-200 flex-none rounded"
                        onClick={() =>
                          setCreateConnectorToggle(
                            (createConnectorToggle) => !createConnectorToggle
                          )
                        }
                      >
                        Create New
                      </button>
                    )}

                    {/* NOTE: connector will never be google_drive, since the ternary above will 
                    prevent that, but still keeping this here for safety in case the above changes. */}
                    {(connector as ValidSources) !== "google_drive" &&
                      createConnectorToggle && (
                        <Modal
                          className="max-w-3xl rounded-lg"
                          onOutsideClick={() => setCreateConnectorToggle(false)}
                        >
                          <>
                            <Title className="mb-2 text-lg">
                              Create a {getSourceDisplayName(connector)}{" "}
                              credential
                            </Title>
                            <CreateCredential
                              close
                              refresh={refresh}
                              sourceType={connector}
                              setPopup={setPopup}
                              onSwitch={onSwap}
                              onClose={() => setCreateConnectorToggle(false)}
                            />
                          </>
                        </Modal>
                      )}
                  </>
                )}
              </Card>
            )}

            {formStep == 1 && (
              <Card className="w-full py-8 flex gap-y-6 flex-col max-w-3xl px-12 mx-auto">
                <DynamicConnectionForm
                  values={formikProps.values}
                  config={configuration}
                  setSelectedFiles={setSelectedFiles}
                  selectedFiles={selectedFiles}
                />

                <IsPublicGroupSelector
                  removeIndent
                  formikProps={formikProps}
                  objectName="Connector"
                />
              </Card>
            )}

            {formStep === 2 && (
              <Card>
                <AdvancedFormPage />
              </Card>
            )}

            <NavigationRow
              activatedCredential={credentialActivated != null}
              isValid={formikProps.isValid}
              onSubmit={formikProps.handleSubmit}
              noCredentials={noCredentials}
              noAdvanced={connector == "file"}
            />
          </div>
        );
      }}
    </Formik>
  );
}
