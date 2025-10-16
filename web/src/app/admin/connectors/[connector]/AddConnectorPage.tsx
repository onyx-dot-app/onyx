"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";

import Title from "@/components/ui/title";
import { AdminPageTitle } from "@/components/admin/Title";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useFormContext } from "@/components/context/FormContext";
import { getSourceDisplayName, getSourceMetadata } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
import { useEffect, useRef, useState } from "react";
import { deleteCredential, linkCredential } from "@/lib/credential";
import { submitFiles } from "./pages/utils/files";
import { submitGoogleSite } from "./pages/utils/google_site";
import AdvancedFormPage from "./pages/Advanced";
import DynamicConnectionForm from "./pages/DynamicConnectorCreationForm";
import CreateCredential from "@/components/credentials/actions/CreateCredential";
import ModifyCredential from "@/components/credentials/actions/ModifyCredential";
import {
  ConfigurableSources,
  oauthSupportedSources,
  ValidSources,
} from "@/lib/types";
import { Credential, credentialTemplates } from "@/lib/connectors/credentials";
import {
  ConnectionConfiguration,
  connectorConfigs,
  createConnectorInitialValues,
  createConnectorValidationSchema,
  defaultPruneFreqHours,
  defaultRefreshFreqMinutes,
  isLoadState,
  Connector,
  ConnectorBase,
} from "@/lib/connectors/connectors";
import { Modal } from "@/components/Modal";
import { GmailMain } from "./pages/gmail/GmailPage";
import {
  useGmailCredentials,
  useGoogleDriveCredentials,
} from "./pages/utils/hooks";
import { Formik } from "formik";
import NavigationRow from "./NavigationRow";
import { useRouter } from "next/navigation";
import CardSection from "@/components/admin/CardSection";
import { prepareOAuthAuthorizationRequest } from "@/lib/oauth_utils";
import {
  EE_ENABLED,
  NEXT_PUBLIC_CLOUD_ENABLED,
  NEXT_PUBLIC_TEST_ENV,
} from "@/lib/constants";
import {
  getConnectorOauthRedirectUrl,
  useOAuthDetails,
} from "@/lib/connectors/oauth";
import { CreateStdOAuthCredential } from "@/components/credentials/actions/CreateStdOAuthCredential";
import { Spinner } from "@/components/Spinner";
import Button from "@/refresh-components/buttons/Button";
import { deleteConnector } from "@/lib/connector";
import ConnectorDocsLink from "@/components/admin/connectors/ConnectorDocsLink";
import Text from "@/refresh-components/texts/Text";

export interface AdvancedConfig {
  refreshFreq: number;
  pruneFreq: number;
  indexingStart: string;
}

const BASE_CONNECTOR_URL = "/api/manage/admin/connector";
const CONNECTOR_CREATION_TIMEOUT_MS = 10000; // ~10 seconds is reasonable for longer connector validation

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
  const [currentPageUrl, setCurrentPageUrl] = useState<string | null>(null);
  const [oauthUrl, setOauthUrl] = useState<string | null>(null);
  const [isAuthorizing, setIsAuthorizing] = useState(false);
  const [isAuthorizeVisible, setIsAuthorizeVisible] = useState(false);
  useEffect(() => {
    if (typeof window !== "undefined") {
      setCurrentPageUrl(window.location.href);
    }

    if (EE_ENABLED && (NEXT_PUBLIC_CLOUD_ENABLED || NEXT_PUBLIC_TEST_ENV)) {
      const sourceMetadata = getSourceMetadata(connector);
      if (sourceMetadata?.oauthSupported == true) {
        setIsAuthorizeVisible(true);
      }
    }
  }, []);

  const router = useRouter();

  // State for managing credentials and files
  const [currentCredential, setCurrentCredential] =
    useState<Credential<any> | null>(null);
  const [createCredentialFormToggle, setCreateCredentialFormToggle] =
    useState(false);

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

  const { data: oauthDetails, isLoading: oauthDetailsLoading } =
    useOAuthDetails(connector);

  // Get credential template and configuration
  const credentialTemplate = credentialTemplates[connector];
  const configuration: ConnectionConfiguration = connectorConfigs[connector];

  // Form context and popup management
  const { setFormStep, setAllowCreate, formStep } = useFormContext();
  const { popup, setPopup } = usePopup();
  const [uploading, setUploading] = useState(false);
  const [creatingConnector, setCreatingConnector] = useState(false);

  // Connector creation timeout management
  const timeoutErrorHappenedRef = useRef<boolean>(false);
  const connectorIdRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      // Cleanup refs when component unmounts
      timeoutErrorHappenedRef.current = false;
      connectorIdRef.current = null;
    };
  }, []);

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

  useEffect(() => {
    if (noCredentials && 1 != formStep) {
      setFormStep(Math.max(1, formStep));
    }

    if (!noCredentials && !credentialActivated && formStep != 0) {
      setFormStep(Math.min(formStep, 0));
    }
  }, [noCredentials, formStep, setFormStep]);

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
    setAllowCreate(true);
    setPopup({
      message: "Swapped credential successfully!",
      type: "success",
    });
    refresh();
  };

  const onSuccess = () => {
    router.push("/admin/indexing/status?message=connector-created");
  };

  const handleAuthorize = async () => {
    // authorize button handler
    // gets an auth url from the server and directs the user to it in a popup

    if (!currentPageUrl) return;

    setIsAuthorizing(true);
    try {
      const response = await prepareOAuthAuthorizationRequest(
        connector,
        currentPageUrl
      );
      if (response.url) {
        setOauthUrl(response.url);
        window.open(response.url, "_blank", "noopener,noreferrer");
      } else {
        setPopup({ message: "Failed to fetch OAuth URL", type: "error" });
      }
    } catch (error: unknown) {
      // Narrow the type of error
      if (error instanceof Error) {
        setPopup({ message: `Error: ${error.message}`, type: "error" });
      } else {
        // Handle non-standard errors
        setPopup({ message: "An unknown error occurred", type: "error" });
      }
    } finally {
      setIsAuthorizing(false);
    }
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

        // Apply special transforms according to application logic
        const transformedConnectorSpecificConfig = Object.entries(
          connector_specific_config
        ).reduce(
          (acc, [key, value]) => {
            // Filter out empty strings from arrays
            if (Array.isArray(value)) {
              value = (value as any[]).filter(
                (item) => typeof item !== "string" || item.trim() !== ""
              );
            }
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
          pruneFreq: (pruneFreq ?? defaultPruneFreqHours) * 3600,
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
          setUploading(true);
          try {
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
          } catch (error) {
            setPopup({ message: "Error uploading files", type: "error" });
          } finally {
            setUploading(false);
          }

          return;
        }

        setCreatingConnector(true);
        try {
          const timeoutPromise = new Promise<{ isTimeout: true }>((resolve) =>
            setTimeout(
              () => resolve({ isTimeout: true }),
              CONNECTOR_CREATION_TIMEOUT_MS
            )
          );

          const connectorCreationPromise = (async () => {
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

            // Store the connector id immediately for potential timeout
            if (response?.id) {
              connectorIdRef.current = response.id;
            }

            // If no credential
            if (!credentialActivated) {
              if (isSuccess) {
                onSuccess();
              } else {
                setPopup({ message: message, type: "error" });
              }
            }

            // With credential
            if (credentialActivated && isSuccess && response) {
              const credential =
                currentCredential ||
                liveGDriveCredential ||
                liveGmailCredential;
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

                if (!timeoutErrorHappenedRef.current) {
                  // Only show error if timeout didn't happen
                  setPopup({
                    message: errorData.message || errorData.detail,
                    type: "error",
                  });
                }
              }
            } else if (isSuccess) {
              onSuccess();
            } else {
              setPopup({ message: message, type: "error" });
            }

            timeoutErrorHappenedRef.current = false;
            return;
          })();

          const result = (await Promise.race([
            connectorCreationPromise,
            timeoutPromise,
          ])) as {
            isTimeout?: true;
          };

          if (result.isTimeout) {
            timeoutErrorHappenedRef.current = true;
            setPopup({
              message: `Operation timed out after ${
                CONNECTOR_CREATION_TIMEOUT_MS / 1000
              } seconds. Check your configuration for errors?`,
              type: "error",
            });

            if (connectorIdRef.current) {
              await deleteConnector(connectorIdRef.current);
              connectorIdRef.current = null;
            }
          }
          return;
        } finally {
          setCreatingConnector(false);
        }
      }}
    >
      {(formikProps) => (
        <div className="mx-auto w-full">
          {popup}

          {uploading && <Spinner />}

          {creatingConnector && <Spinner />}

          <AdminPageTitle
            includeDivider={false}
            icon={<SourceIcon iconSize={32} sourceType={connector} />}
            title={displayName}
            farRightElement={undefined}
          />

          {formStep == 0 && (
            <CardSection>
              <Text headingH3 className="pb-2">
                Select a credential
              </Text>

              {connector == ValidSources.Gmail ? (
                <GmailMain />
              ) : (
                <>
                  <ModifyCredential
                    showIfEmpty
                    accessType={formikProps.values.access_type}
                    defaultedCredential={currentCredential!}
                    credentials={credentials}
                    editableCredentials={editableCredentials}
                    onDeleteCredential={onDeleteCredential}
                    onSwitch={onSwap}
                  />
                  {!createCredentialFormToggle && (
                    <div className="mt-6 flex space-x-4">
                      {/* Button to pop up a form to manually enter credentials */}
                      <Button
                        onClick={async () => {
                          if (oauthDetails && oauthDetails.oauth_enabled) {
                            if (oauthDetails.additional_kwargs.length > 0) {
                              setCreateCredentialFormToggle(true);
                            } else {
                              const redirectUrl =
                                await getConnectorOauthRedirectUrl(
                                  connector,
                                  {}
                                );
                              // if redirect is supported, just use it
                              if (redirectUrl) {
                                window.location.href = redirectUrl;
                              } else {
                                setCreateCredentialFormToggle(
                                  (createConnectorToggle) =>
                                    !createConnectorToggle
                                );
                              }
                            }
                          } else {
                            setCreateCredentialFormToggle(
                              (createConnectorToggle) => !createConnectorToggle
                            );
                          }
                        }}
                      >
                        Create New
                      </Button>
                      {/* Button to sign in via OAuth */}
                      {oauthSupportedSources.includes(connector) &&
                        (NEXT_PUBLIC_CLOUD_ENABLED || NEXT_PUBLIC_TEST_ENV) && (
                          <Button
                            action
                            onClick={handleAuthorize}
                            disabled={isAuthorizing}
                            hidden={!isAuthorizeVisible}
                          >
                            {isAuthorizing
                              ? "Authorizing..."
                              : `Authorize with ${getSourceDisplayName(
                                  connector
                                )}`}
                          </Button>
                        )}
                    </div>
                  )}

                  {createCredentialFormToggle && (
                    <Modal
                      className="max-w-3xl rounded-lg"
                      onOutsideClick={() =>
                        setCreateCredentialFormToggle(false)
                      }
                    >
                      {oauthDetailsLoading ? (
                        <Spinner />
                      ) : (
                        <>
                          <Title className="mb-2 text-lg">
                            Create a {getSourceDisplayName(connector)}{" "}
                            credential
                          </Title>
                          {oauthDetails && oauthDetails.oauth_enabled ? (
                            <CreateStdOAuthCredential
                              sourceType={connector}
                              additionalFields={oauthDetails.additional_kwargs}
                            />
                          ) : (
                            <CreateCredential
                              close
                              refresh={refresh}
                              sourceType={connector}
                              accessType={formikProps.values.access_type}
                              setPopup={setPopup}
                              onSwitch={onSwap}
                              onClose={() =>
                                setCreateCredentialFormToggle(false)
                              }
                            />
                          )}
                        </>
                      )}
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
              <ConnectorDocsLink sourceType={connector} />
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
      )}
    </Formik>
  );
}
