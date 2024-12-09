"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { HealthCheckBanner } from "@/components/health/healthcheck";

import Title from "@/components/ui/title";
import { AdminPageTitle } from "@/components/admin/Title";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useFormContext } from "@/components/context/FormContext";
import { getSourceDisplayName } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
import { useState } from "react";
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
  defaultPruneFreqDays,
  defaultRefreshFreqMinutes,
  isLoadState,
  Connector,
  ConnectorBase,
} from "@/lib/connectors/connectors";
import { Modal } from "@/components/Modal";
import GDriveMain from "./pages/gdrive/GoogleDrivePage";
import { GmailMain } from "./pages/gmail/GmailPage";
import {
  useGmailCredentials,
  useGoogleDriveCredentials,
} from "./pages/utils/hooks";
import { Formik } from "formik";
import NavigationRow from "./NavigationRow";
import { useRouter } from "next/navigation";
import CardSection from "@/components/admin/CardSection";
export interface AdvancedConfig {
  refreshFreq: number;
  pruneFreq: number;
  indexingStart: string;
}

const BASE_CONNECTOR_URL = "/api/manage/admin/connector";

export async function submitConnector<T>(
  connector: ConnectorBase<T>,
  connectorId?: number,
  fakeCredential?: boolean
): Promise<{ message: string; isSuccess: boolean; response?: Connector<T> }> {
  const isUpdate = connectorId !== undefined;
  if (!connector.connector_specific_config) {
    connector.connector_specific_config = {} as T;
  }

  try {
    if (fakeCredential) {
      const response = await fetch(
        "/api/manage/admin/connector-with-mock-credential",
        {
          method: isUpdate ? "PATCH" : "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ ...connector }),
        }
      );
      if (response.ok) {
        const responseJson = await response.json();
        return { message: "Success!", isSuccess: true, response: responseJson };
      } else {
        const errorData = await response.json();
        return { message: `Error: ${errorData.detail}`, isSuccess: false };
      }
    } else {
      const response = await fetch(
        BASE_CONNECTOR_URL + (isUpdate ? `/${connectorId}` : ""),
        {
          method: isUpdate ? "PATCH" : "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(connector),
        }
      );

      if (response.ok) {
        const responseJson = await response.json();
        return { message: "Success!", isSuccess: true, response: responseJson };
      } else {
        const errorData = await response.json();
        return { message: `Error: ${errorData.detail}`, isSuccess: false };
      }
    }
  } catch (error) {
    return { message: `Error: ${error}`, isSuccess: false };
  }
}

export default function AddConnector({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  const router = useRouter();

  // State for managing credentials and files
  const [currentCredential, setCurrentCredential] =
    useState<Credential<any> | null>(null);
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
  const { liveGDriveCredential } = useGoogleDriveCredentials(connector);
  const { liveGmailCredential } = useGmailCredentials(connector);

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
    router.push("/admin/indexing/status?message=connector-created");
  };

  return (
    <Formik
      initialValues={{
        ...createConnectorInitialValues(connector),
        ...Object.fromEntries(
          connectorConfigs[connector].advanced_values.map((field) => [
            field.name,
            field.default || "",
          ])
        ),
      }}
      validationSchema={createConnectorValidationSchema(connector)}
      onSubmit={async (values) => {
        const {
          name,
          groups,
          access_type,
          pruneFreq,
          indexingStart,
          refreshFreq,
          auto_sync_options,
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
          pruneFreq: (pruneFreq ?? defaultPruneFreqDays) * 60 * 60 * 24,
          indexingStart: convertStringToDateTime(indexingStart),
          refreshFreq: (refreshFreq ?? defaultRefreshFreqMinutes) * 60,
        };

        // File-specific handling
        const selectedFiles = Array.isArray(values.file_locations)
          ? values.file_locations
          : values.file_locations
            ? [values.file_locations]
            : [];

        // Google sites-specific handling
        if (connector == "google_sites") {
          const response = await submitGoogleSite(
            selectedFiles,
            values?.base_url,
            setPopup,
            advancedConfiguration.refreshFreq,
            advancedConfiguration.pruneFreq,
            advancedConfiguration.indexingStart,
            values.access_type,
            groups,
            name
          );
          if (response) {
            onSuccess();
          }
          return;
        }
        // File-specific handling
        if (connector == "file") {
          const response = await submitFiles(
            selectedFiles,
            setPopup,
            name,
            access_type,
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
            input_type: isLoadState(connector) ? "load_state" : "poll", // single case
            name: name,
            source: connector,
            access_type: access_type,
            refresh_freq: advancedConfiguration.refreshFreq || null,
            prune_freq: advancedConfiguration.pruneFreq || null,
            indexing_start: advancedConfiguration.indexingStart || null,
            groups: groups,
          },
          undefined,
          credentialActivated ? false : true
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
            access_type,
            groups,
            auto_sync_options
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
              <CardSection>
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
              </CardSection>
            )}

            {formStep == 1 && (
              <CardSection className="w-full py-8 flex gap-y-6 flex-col max-w-3xl px-12 mx-auto">
                <DynamicConnectionForm
                  values={formikProps.values}
                  config={configuration}
                  connector={connector}
                  currentCredential={
                    currentCredential ||
                    liveGDriveCredential ||
                    liveGmailCredential ||
                    null
                  }
                />
              </CardSection>
            )}

            {formStep === 2 && (
              <CardSection>
                <AdvancedFormPage />
              </CardSection>
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
