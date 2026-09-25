"use client";

import { errorHandlingFetcher } from "@/lib/fetcher";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import useSWR, { mutate } from "swr";
import { buildSimilarCredentialInfoURL } from "@/lib/connectors/utils";
import { getSourceDisplayName, getSourceMetadata } from "@/lib/sources";
import { useEffect, useRef, useState } from "react";
import { Logo } from "@/lib/app/components";
import { deleteCredential, linkCredential } from "@/lib/credential";
import { submitFiles } from "@/lib/connectors/svc";
import { submitGoogleSite } from "@/lib/connectors/svc";
import AdvancedFormPage from "@/views/admin/connectors/AddConnectorPage/form/Advanced";
import DynamicConnectionForm from "@/views/admin/connectors/AddConnectorPage/form/DynamicConnectorCreationForm";
import CreateCredential from "@/lib/credentials/components/CreateCredential";
import { CreateStdOAuthCredential } from "@/lib/credentials/components/CreateStdOAuthCredential";
import {
  CredentialCreationMethod,
  getCredentialCreationActionLabel,
  getCredentialCreationMethods,
  shouldRedirectToOAuth,
} from "@/lib/credentials/credentialCreation";
import ModifyCredential from "@/lib/credentials/components/ModifyCredential";
import {
  ConfigurableSources,
  oauthSupportedSources,
  ValidSources,
} from "@/lib/types";
import { credentialTemplates } from "@/lib/connectors/credentials";
import type { Credential } from "@/lib/connectors/types";
import {
  connectorConfigs,
  defaultRefreshFreqMinutes,
} from "@/lib/connectors/connectors";
import {
  createConnectorInitialValues,
  createConnectorValidationSchema,
  isLoadState,
} from "@/lib/connectors/utils";
import type {
  ConnectionConfiguration,
  Connector,
  ConnectorBase,
} from "@/lib/connectors/types";
import { useSettings } from "@/lib/settings/hooks";
import { Card, MessageCard, Modal } from "@opal/components";
import { Disabled } from "@opal/core";
import {
  useGmailCredentials,
  useGoogleDriveCredentials,
} from "@/lib/connectors/hooks";
import { Formik } from "formik";
import { useRouter } from "next/navigation";
import { prepareOAuthAuthorizationRequest } from "@/lib/oauth_utils";
import {
  EE_ENABLED,
  NEXT_PUBLIC_CLOUD_ENABLED,
  NEXT_PUBLIC_TEST_ENV,
} from "@/lib/constants";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/svc";
import { useOAuthDetails } from "@/lib/connectors/hooks";
import { Button, Text as OpalText } from "@opal/components";
import { Content, Section, SettingsLayouts, toast } from "@opal/layouts";
import {
  deleteConnector,
  discardConnectorAfterFailedLink,
} from "@/lib/connector";
import ConnectorDocsLink from "@/components/admin/connectors/ConnectorDocsLink";
import { SvgArrowExchange, SvgKey, SvgSimpleLoader } from "@opal/icons";
import { useTranslations } from "next-intl";
import { toWireAccess } from "@/lib/connectors/accessType";

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
): Promise<{
  errorDetail?: string;
  isSuccess: boolean;
  response?: Connector<T>;
}> {
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
        return { isSuccess: true, response: responseJson };
      } else {
        const errorData = await response.json();
        return { errorDetail: String(errorData.detail), isSuccess: false };
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
        return { isSuccess: true, response: responseJson };
      } else {
        const errorData = await response.json();
        return { errorDetail: String(errorData.detail), isSuccess: false };
      }
    }
  } catch (error) {
    return { errorDetail: String(error), isSuccess: false };
  }
}

export default function AddConnector({
  connector,
}: {
  connector: ConfigurableSources;
}) {
  const t = useTranslations("admin.connectorsList");
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
  const settings = useSettings();
  const defaultPruneFreqHours = settings.default_pruning_freq
    ? settings.default_pruning_freq / 3600
    : 600; // 25 days fallback until settings load

  // State for managing credentials and files
  const [currentCredential, setCurrentCredential] =
    useState<Credential<any> | null>(null);
  const [credentialCreationMethod, setCredentialCreationMethod] =
    useState<CredentialCreationMethod | null>(null);

  const { isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );

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

  // Sources without a credential template skip the credential section.
  const noCredentials = credentialTemplate == null;
  const canCreate = noCredentials || credentialActivated != null;

  const convertStringToDateTime = (indexingStart: string | null) => {
    return indexingStart ? new Date(indexingStart) : null;
  };

  const displayName = getSourceDisplayName(connector) || connector;
  const sourceMetadata = getSourceMetadata(connector);
  const hasFederatedOption = sourceMetadata.federated === true;
  const credentialCreationMethods = getCredentialCreationMethods(oauthDetails);
  const showExplicitCredentialMethods = credentialCreationMethods.length > 1;

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
      toast.success(t("add.credentialDeleted.toast"));
    } else {
      const errorData = await response.json();
      toast.error(errorData.detail || errorData.message);
    }
  };

  const onSwap = async (selectedCredential: Credential<any>) => {
    setCurrentCredential(selectedCredential);
    toast.success(t("add.credentialSwapped.toast"));
    refresh();
  };

  const onSuccess = () => {
    router.push("/admin/indexing-status?message=connector-created");
  };

  const closeCredentialModal = () => setCredentialCreationMethod(null);

  const attemptOauthRedirect = async () => {
    try {
      const redirectUrl = await getConnectorOauthRedirectUrl(connector, {});
      window.location.href = redirectUrl;
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("add.oauthStartFailed.toast")
      );
    }
  };

  const openCredentialCreationMethod = async (
    method: CredentialCreationMethod
  ) => {
    if (
      method === CredentialCreationMethod.OAuth &&
      oauthDetails &&
      shouldRedirectToOAuth(oauthDetails)
    ) {
      await attemptOauthRedirect();
      return;
    }
    if (method === CredentialCreationMethod.OAuth && !oauthDetails) {
      return;
    }
    setCredentialCreationMethod(method);
  };

  const handleAuthorize = async () => {
    // authorize button handler
    // gets an auth url from the server and directs the user to it in a popup

    if (!currentPageUrl) return;

    setIsAuthorizing(true);
    try {
      const response = await prepareOAuthAuthorizationRequest(
        connector,
        currentPageUrl,
        t("add.oauthStartFailed.toast")
      );
      if (response.url) {
        setOauthUrl(response.url);
        window.open(response.url, "_blank", "noopener,noreferrer");
      } else {
        toast.error(t("add.oauthUrlFailed.toast"));
      }
    } catch (error: unknown) {
      // Narrow the type of error
      if (error instanceof Error) {
        toast.error(t("add.error.toast", { detail: error.message }));
      } else {
        // Handle non-standard errors
        toast.error(t("add.unknownError.toast"));
      }
    } finally {
      setIsAuthorizing(false);
    }
  };

  return (
    <Formik
      initialValues={createConnectorInitialValues(connector)}
      validationSchema={createConnectorValidationSchema(
        connector,
        isScopedManager
      )}
      onSubmit={async (values) => {
        const {
          name,
          groups,
          access_type: formAccessType,
          restrict_access_to_groups,
          restriction_group_ids,
          pruneFreq,
          indexingStart,
          refreshFreq,
          auto_sync_options,
          ...connector_specific_config
        } = values;

        const wireAccess = toWireAccess(formAccessType, {
          restrict_access_to_groups,
          restriction_group_ids,
        });
        const access_type = wireAccess.access_type;

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
              name,
              access_type,
              groups
            );
            if (response) {
              onSuccess();
            }
          } catch (error) {
            toast.error(t("add.fileUploadFailed.toast"));
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
            const { errorDetail, isSuccess, response } =
              await submitConnector<any>(
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

            if (!credentialActivated) {
              if (isSuccess) {
                onSuccess();
              } else {
                toast.error(
                  t("add.error.toast", { detail: errorDetail ?? "" })
                );
              }
              timeoutErrorHappenedRef.current = false;
              return;
            }

            // With credential
            if (credentialActivated && isSuccess && response) {
              const credential =
                currentCredential ||
                liveGDriveCredential ||
                liveGmailCredential;
              // TODO(evan, ENG-4342): send wireAccess.restriction_group_ids
              // once the backend accepts them; this call creates the cc-pair.
              const linkCredentialResponse = await linkCredential(
                response.id,
                credential!.id,
                name,
                access_type,
                groups,
                auto_sync_options
              );
              if (linkCredentialResponse.ok) {
                onSuccess();
              } else {
                const errorData = await linkCredentialResponse.json();
                const discarded = await discardConnectorAfterFailedLink(
                  response.id,
                  linkCredentialResponse.status
                );
                if (discarded && connectorIdRef.current === response.id) {
                  connectorIdRef.current = null;
                }

                if (!timeoutErrorHappenedRef.current) {
                  // Only show error if timeout didn't happen
                  toast.error(errorData.detail || errorData.message);
                }
              }
            } else if (isSuccess) {
              onSuccess();
            } else {
              toast.error(t("add.error.toast", { detail: errorDetail ?? "" }));
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
            toast.error(
              t("add.timeout.toast", {
                seconds: CONNECTOR_CREATION_TIMEOUT_MS / 1000,
              })
            );

            if (connectorIdRef.current) {
              // The link may still land after the timeout. Never cascade it.
              await deleteConnector(connectorIdRef.current, {
                onlyUnpaired: true,
              });
              connectorIdRef.current = null;
            }
          }
          return;
        } finally {
          setCreatingConnector(false);
        }
      }}
    >
      {(formikProps) => {
        const busy = uploading || creatingConnector;
        return (
          <SettingsLayouts.Root width="sm">
            <SettingsLayouts.Header
              icon={sourceMetadata.icon}
              moreIcon1={SvgArrowExchange}
              moreIcon2={Logo}
              title={displayName}
              description={t("header.description", {
                source: displayName,
                appName: settings.appName,
              })}
              divider
              actions={[
                <Button
                  key="cancel"
                  prominence="secondary"
                  disabled={busy}
                  onClick={() => router.push("/admin/connectors")}
                >
                  {t("header.cancelButton.label")}
                </Button>,
                <Button
                  key="connect"
                  disabled={!formikProps.isValid || !canCreate || busy}
                  icon={busy ? SvgSimpleLoader : undefined}
                  onClick={() => formikProps.handleSubmit()}
                >
                  {t("header.connectButton.label")}
                </Button>,
              ]}
            >
              {hasFederatedOption && (
                <MessageCard
                  variant="info"
                  title={t("add.federated.tooltip.description")}
                  bottomChildren={
                    <Button
                      prominence="secondary"
                      onClick={() =>
                        router.push(
                          `/admin/connectors/${connector}?mode=federated`
                        )
                      }
                    >
                      {t("add.federated.tooltip.link.label")}
                    </Button>
                  }
                />
              )}
            </SettingsLayouts.Header>

            <SettingsLayouts.Body>
              <Section gap={4} alignItems="stretch" width="full">
                {!noCredentials && (
                  <Card border="solid" rounding={4} padding={6}>
                    <Section gap={4} alignItems="start" width="full">
                      <Content
                        title={t("add.credentialStep.title")}
                        sizePreset="main-content"
                        variant="section"
                      />

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
                        {credentialCreationMethod === null && (
                          <Section
                            flexDirection="row"
                            justifyContent="start"
                            gap={1}
                            className="mt-6"
                          >
                            {oauthDetailsLoading ? (
                              <Button disabled>
                                {t("add.createCredentialButton.label")}
                              </Button>
                            ) : (
                              credentialCreationMethods.map((method) => (
                                <Button
                                  key={method}
                                  onClick={() =>
                                    openCredentialCreationMethod(method)
                                  }
                                >
                                  {getCredentialCreationActionLabel(
                                    method,
                                    displayName,
                                    showExplicitCredentialMethods
                                  )}
                                </Button>
                              ))
                            )}
                            {oauthSupportedSources.includes(connector) &&
                              (NEXT_PUBLIC_CLOUD_ENABLED ||
                                NEXT_PUBLIC_TEST_ENV) && (
                                <Button
                                  disabled={isAuthorizing}
                                  variant="action"
                                  onClick={handleAuthorize}
                                  hidden={!isAuthorizeVisible}
                                >
                                  {isAuthorizing
                                    ? t("add.authorizeButton.pendingLabel")
                                    : t("add.authorizeButton.label", {
                                        source: displayName,
                                      })}
                                </Button>
                              )}
                          </Section>
                        )}

                        {credentialCreationMethod !== null && (
                          <Modal open onOpenChange={closeCredentialModal}>
                            <Modal.Content>
                              <Modal.Header
                                icon={SvgKey}
                                title={t("add.credentialModal.title", {
                                  source: displayName,
                                })}
                                onClose={closeCredentialModal}
                              />
                              <Modal.Body alignItems="stretch">
                                {oauthDetailsLoading ? null : credentialCreationMethod ===
                                    CredentialCreationMethod.OAuth &&
                                  oauthDetails ? (
                                  shouldRedirectToOAuth(oauthDetails) ? (
                                    <Section alignItems="start">
                                      <OpalText
                                        as="p"
                                        font="main-ui-body"
                                        color="text-03"
                                      >
                                        {t("add.oauthRedirectFailed.message", {
                                          source: displayName,
                                        })}
                                      </OpalText>
                                      <Button onClick={attemptOauthRedirect}>
                                        {t("add.retryButton.label")}
                                      </Button>
                                    </Section>
                                  ) : (
                                    <CreateStdOAuthCredential
                                      sourceType={connector}
                                      additionalFields={
                                        oauthDetails.additional_kwargs
                                      }
                                    />
                                  )
                                ) : (
                                  <CreateCredential
                                    close
                                    refresh={refresh}
                                    sourceType={connector}
                                    accessType={formikProps.values.access_type}
                                    onSwitch={onSwap}
                                    onClose={closeCredentialModal}
                                  />
                                )}
                              </Modal.Body>
                            </Modal.Content>
                          </Modal>
                        )}
                      </>
                    </Section>
                  </Card>
                )}

                {/* The wizard could not reach these sections without a
                    credential; on one page they stay disabled until one is
                    selected instead. */}
                <Disabled
                  disabled={!canCreate}
                  tooltip={t("credentialRequired.tooltip")}
                >
                  <Card
                    border="solid"
                    rounding={4}
                    padding={6}
                    disabled={!canCreate}
                  >
                    {/* A disabled fieldset also takes the controls out of the
                        tab order; the wrapper above only blocks the pointer. */}
                    <fieldset disabled={!canCreate} className="contents">
                      <Section gap={4} alignItems="start" width="full">
                        <Content
                          title={t("sections.configuration.title")}
                          sizePreset="main-content"
                          variant="section"
                        />
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
                      </Section>
                    </fieldset>
                  </Card>
                </Disabled>

                {connector !== "file" && (
                  <Disabled
                    disabled={!canCreate}
                    tooltip={t("credentialRequired.tooltip")}
                  >
                    <Card
                      border="solid"
                      rounding={4}
                      padding={6}
                      disabled={!canCreate}
                    >
                      <fieldset disabled={!canCreate} className="contents">
                        <AdvancedFormPage
                          defaultPruneFreqHours={defaultPruneFreqHours}
                        />
                      </fieldset>
                    </Card>
                  </Disabled>
                )}
              </Section>
            </SettingsLayouts.Body>
          </SettingsLayouts.Root>
        );
      }}
    </Formik>
  );
}
