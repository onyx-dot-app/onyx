"use client";

import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import {
  getSourceDisplayName,
  getSourceDocLink,
  getSourceMetadata,
} from "@/lib/sources";
import { useEffect, useRef, useState } from "react";
import { Logo } from "@/lib/app/components";
import { linkCredential } from "@/lib/credential";
import { CredentialsConfigurer } from "@/lib/connectors/components";
import { submitFiles } from "@/lib/connectors/svc";
import { submitGoogleSite } from "@/lib/connectors/svc";
import AdvancedFormPage from "@/views/admin/connectors/AddConnectorPage/form/Advanced";
import DynamicConnectionForm from "@/views/admin/connectors/AddConnectorPage/form/DynamicConnectorCreationForm";
import { ConfigurableSources, ValidSources } from "@/lib/types";
import { credentialTemplates } from "@/lib/connectors/credentials";
import type { Credential } from "@/lib/connectors/types";
import {
  defaultRefreshFreqMinutes,
  useConnectorConfiguration,
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
import { Card, MessageCard } from "@opal/components";
import { Disabled } from "@opal/core";
import {
  useGmailCredentials,
  useGoogleDriveCredentials,
} from "@/lib/connectors/hooks";
import { Formik } from "formik";
import { useRouter } from "next/navigation";
import { Button } from "@opal/components";
import { Content, Section, SettingsLayouts, toast } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { deleteConnector } from "@/lib/connector";
import { SvgArrowExchange, SvgSimpleLoader } from "@opal/icons";
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
  const oneDriveT = useTranslations("admin.connectorsList.oneDrive");
  const router = useRouter();
  const settings = useSettings();
  const defaultPruneFreqHours = settings.default_pruning_freq
    ? settings.default_pruning_freq / 3600
    : 600; // 25 days fallback until settings load

  // State for managing credentials and files
  const [currentCredential, setCurrentCredential] =
    useState<Credential<any> | null>(null);

  const { isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );

  // Get credential template and configuration
  const credentialTemplate = credentialTemplates[connector];
  const configuration: ConnectionConfiguration =
    useConnectorConfiguration(connector);
  const formControlFieldNames = new Set(
    [...configuration.values, ...configuration.advanced_values]
      .filter((field) => field.type === "tab")
      .map((field) => field.name)
  );

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

  // The docs sit at the end of the header sentence, so the whole page has
  // one pointer to them rather than one per form. One message holds both,
  // so translators place the link.
  const docsLink = getSourceDocLink(connector);
  const headerSentence = t("header.description", {
    source: displayName,
    appName: settings.appName,
    hasDocs: docsLink ? "true" : "false",
    url: docsLink ?? "",
  });
  const headerDescription = docsLink
    ? markdown(headerSentence)
    : headerSentence;
  const sourceMetadata = getSourceMetadata(connector);
  const hasFederatedOption = sourceMetadata.federated === true;
  const onSuccess = () => {
    router.push("/admin/indexing-status?message=connector-created");
  };

  return (
    <Formik
      initialValues={createConnectorInitialValues(connector)}
      validationSchema={createConnectorValidationSchema(
        connector,
        isScopedManager,
        {
          oneDriveUsersRequired: oneDriveT(
            "indexingScope.specific.users.required"
          ),
        }
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
            if (formControlFieldNames.has(key)) {
              return acc;
            }
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
      {(formikProps) => {
        const busy = uploading || creatingConnector;
        return (
          <SettingsLayouts.Root width="sm">
            <SettingsLayouts.Header
              icon={sourceMetadata.icon}
              moreIcon1={SvgArrowExchange}
              moreIcon2={Logo}
              title={displayName}
              description={headerDescription}
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
                  <CredentialsConfigurer
                    connector={connector}
                    accessType={formikProps.values.access_type}
                    currentCredential={currentCredential}
                    onCredentialChange={setCurrentCredential}
                  />
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
                    <fieldset
                      disabled={!canCreate}
                      className="contents"
                      data-testid="connector-form"
                    >
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
