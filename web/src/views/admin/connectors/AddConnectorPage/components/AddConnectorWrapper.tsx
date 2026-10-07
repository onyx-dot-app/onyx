"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Formik } from "formik";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { PageLoader, IconLoader } from "@opal/loaders";
import {
  IllustrationContent,
  PageCenter,
  Section,
  SettingsLayouts,
  toast,
  useToastFromQuery,
} from "@opal/layouts";
import { SvgPlugBroken } from "@opal/illustrations";
import { escapeMarkdown, markdown } from "@opal/utils";
import { Button, Divider, MessageCard } from "@opal/components";
import { SvgAlertCircle, SvgArrowExchange } from "@opal/icons";
import { Disabled } from "@opal/core";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import {
  getSourceDisplayName,
  getSourceDocLink,
  getSourceMetadata,
  isValidSource,
} from "@/lib/sources";
import { Logo } from "@/lib/app/components";
import { linkCredential } from "@/lib/credentials/svc";
import { submitFiles, submitGoogleSite } from "@/lib/connectors/svc";
import {
  useBindingGateMessage,
  type UseBoundFieldsGateResult,
} from "@/lib/connectors/hooks";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import { getCredentialSpec } from "@/lib/credentials/utils";
import type { Credential } from "@/lib/credentials/types";
import {
  defaultRefreshFreqMinutes,
  useConnectorConfiguration,
} from "@/lib/connectors/connectors";
import {
  createConnectorInitialValues,
  createConnectorValidationSchema,
  isLoadState,
  splitCredentialBoundFields,
} from "@/lib/connectors/utils";
import type {
  ConnectionConfiguration,
  Connector,
  ConnectorBase,
} from "@/lib/connectors/types";
import { useSettings } from "@/lib/settings/hooks";
import {
  useGmailCredentials,
  useCredentialLoad,
  useGoogleDriveCredentials,
} from "@/lib/credentials/hooks";
import { deleteConnector } from "@/lib/connector";
import {
  SYNC_RESTRICTED_ACCESS_TYPE,
  toManageAccess,
  toWireAccess,
} from "@/lib/connectors/accessType";
import { FederatedConnectorForm } from "@/components/admin/federated/FederatedConnectorForm";
import AuthenticationAccountSection from "@/views/admin/connectors/AddConnectorPage/sections/AuthenticationAccountSection";
import ConnectorContentSection from "@/views/admin/connectors/AddConnectorPage/sections/ConnectorContentSection";
import ConnectorSettingsSection from "@/views/admin/connectors/AddConnectorPage/sections/ConnectorSettingsSection";
import ScheduleSection from "@/views/admin/connectors/AddConnectorPage/sections/ScheduleSection";
import CredentialBoundFields from "@/views/admin/connectors/AddConnectorPage/form/CredentialBoundFields";
import { BoundFieldsGate } from "@/views/admin/connectors/AddConnectorPage/form/BoundFieldsGate";

const BASE_CONNECTOR_URL = "/api/manage/admin/connector";
const CONNECTOR_CREATION_TIMEOUT_MS = 10000; // ~10 seconds is reasonable for longer connector validation

async function submitConnector<T>(
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

interface AddConnectorFormProps {
  connector: ConfigurableSources;
}

/**
 * The setup form for one valid, non-federated source. It is its own
 * component so its hooks never run behind the wrapper's early returns.
 */
function AddConnectorForm({ connector }: AddConnectorFormProps) {
  const t = useTranslations("admin.connectorsList");
  const oneDriveT = useTranslations("admin.connectorsList.oneDrive");
  // The string-pair editor (InputKeyValue) shows these same messages.
  const keyValueT = useTranslations("opal.keyValue");
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

  // Get credential spec and configuration
  const credentialSpec = getCredentialSpec(connector);
  const configuration: ConnectionConfiguration =
    useConnectorConfiguration(connector);
  // Fields bound to the credential sit above the credential section. The
  // submit below still reads the full configuration.
  const credentialBoundFields = splitCredentialBoundFields(
    connector,
    configuration
  );
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

  // Sources without a credential spec skip the credential section.
  const noCredentials = credentialSpec == null;
  const canCreate = noCredentials || credentialActivated != null;

  // The page body waits for the source's saved credentials: no connector
  // can be set up without them. Sources without credentials fetch nothing and go
  // straight to the form. The credential step calls the same hook; SWR
  // shares the requests.
  const { isLoading: credentialsLoading, error: credentialLoadError } =
    useCredentialLoad(connector, { enabled: !noCredentials });

  // The configuration unlocks once the credential and the credential-bound
  // fields are a valid combination. `BoundFieldsGate` reports it.
  const [gate, setGate] = useState<UseBoundFieldsGateResult | null>(null);
  const onGateChange = useCallback(
    (next: UseBoundFieldsGateResult) => setGate(next),
    []
  );
  const configUnlocked = gate?.status === "unlocked";
  const gateMessage = useBindingGateMessage(gate?.reason ?? null);
  // The rest of the form also waits for the capability checks, which the
  // Authentication Account section reports. Sources without a credential
  // step have no checks.
  const [checksPassed, setChecksPassed] = useState<boolean>(false);
  const onChecksPassedChange = useCallback(
    (passed: boolean) => setChecksPassed(passed),
    []
  );
  const checksT = useTranslations("admin.connectorChecks");
  const formUnlocked: boolean =
    configUnlocked && (noCredentials || checksPassed);
  const formLockReason: string | undefined = !configUnlocked
    ? (gateMessage ?? undefined)
    : formUnlocked
      ? undefined
      : checksT("lockReason");

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
    // Admin-set, so escaped whenever the sentence is parsed as markdown.
    appName: docsLink ? escapeMarkdown(settings.appName) : settings.appName,
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

  const credentialsFailed = credentialLoadError !== undefined;

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
          specificGroupsRequired: t(
            "settings.documentAccess.specificGroups.required"
          ),
          stringPairEmptyKey: keyValueT("emptyKey"),
          stringPairDuplicateKey: keyValueT("duplicateKey"),
        }
      )}
      onSubmit={async (values) => {
        const {
          name,
          groups,
          group_roles,
          data_access_group_ids,
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
        // A private connector's readers; its `groups` are its managers, each
        // with a role.
        const dataAccess =
          access_type === "private" ? data_access_group_ids : undefined;
        const manageAccess = toManageAccess(groups, group_roles);

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
          // The backend stores whole seconds.
          pruneFreq: Math.round((pruneFreq ?? defaultPruneFreqHours) * 3600),
          indexingStart: convertStringToDateTime(indexingStart),
          refreshFreq: Math.round(
            (refreshFreq ?? defaultRefreshFreqMinutes) * 60
          ),
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
            name,
            dataAccess,
            manageAccess
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
              groups,
              dataAccess,
              manageAccess
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
              const linkCredentialResponse = await linkCredential(
                response.id,
                credential!.id,
                name,
                access_type,
                groups,
                auto_sync_options,
                undefined,
                access_type === SYNC_RESTRICTED_ACCESS_TYPE
                  ? wireAccess.restriction_group_ids
                  : dataAccess,
                manageAccess
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
        const formCredential =
          currentCredential ||
          liveGDriveCredential ||
          liveGmailCredential ||
          null;
        const showAdvancedBoundFields =
          !configuration.advancedValuesVisibleCondition ||
          configuration.advancedValuesVisibleCondition(
            formikProps.values,
            formCredential
          );
        const visibleBoundFields = [
          ...credentialBoundFields.values,
          ...(showAdvancedBoundFields
            ? credentialBoundFields.advancedValues
            : []),
        ].filter((field) => !field.hidden);
        const hasVisibleBoundFields = visibleBoundFields.length > 0;
        return (
          <SettingsLayouts.Root width="sm">
            <SettingsLayouts.Header
              icon={sourceMetadata.icon}
              moreIcon1={SvgArrowExchange}
              moreIcon2={Logo}
              title={displayName}
              // Failed, the page offers nothing to set up, so the header drops
              // its docs pointer; the Connect button stays, disabled.
              description={
                credentialsFailed
                  ? t("header.description", {
                      source: displayName,
                      appName: settings.appName,
                      hasDocs: "false",
                      url: "",
                    })
                  : headerDescription
              }
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
                // Always present; disabled while the credentials load or
                // after they fail, since nothing can be connected then.
                <Button
                  key="connect"
                  disabled={
                    credentialsLoading ||
                    credentialsFailed ||
                    !formikProps.isValid ||
                    !formUnlocked ||
                    busy
                  }
                  icon={busy ? IconLoader : undefined}
                  onClick={() => formikProps.handleSubmit()}
                >
                  {t("header.connectButton.label")}
                </Button>,
              ]}
            >
              {hasFederatedOption && (
                <MessageCard
                  variant="info"
                  title={t("add.federated.tooltip.title")}
                  description={t("add.federated.tooltip.description")}
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
              {credentialsLoading ? (
                <PageLoader />
              ) : credentialsFailed ? (
                // The same frame as PageLoader, so loading and failure sit
                // in one place.
                <PageCenter>
                  <IllustrationContent
                    illustration={SvgPlugBroken}
                    title={t("add.credentialsLoadFailed.title")}
                    description={t("add.credentialsLoadFailed.description")}
                  />
                </PageCenter>
              ) : (
                <>
                  <BoundFieldsGate
                    source={connector}
                    credentialId={
                      noCredentials ? null : (formCredential?.id ?? null)
                    }
                    credentialSelected={canCreate}
                    currentCredential={formCredential}
                    allBoundFields={[
                      ...credentialBoundFields.values,
                      ...credentialBoundFields.advancedValues,
                    ]}
                    visibleBoundFields={visibleBoundFields}
                    onChange={onGateChange}
                  />
                  <Section gap={6} alignItems="stretch" width="full">
                    {hasVisibleBoundFields && (
                      <>
                        <CredentialBoundFields
                          fields={credentialBoundFields.values}
                          advancedFields={credentialBoundFields.advancedValues}
                          showAdvancedFields={showAdvancedBoundFields}
                          values={formikProps.values}
                          connector={connector}
                          currentCredential={formCredential}
                          fieldErrors={gate?.fieldErrors}
                          onFieldBlur={gate?.requestCheck}
                        />
                        {!noCredentials && (
                          <Divider
                            paddingParallel={0}
                            paddingPerpendicular={0}
                          />
                        )}
                      </>
                    )}

                    {!noCredentials && (
                      <AuthenticationAccountSection
                        connector={connector}
                        accessType={formikProps.values.access_type}
                        currentCredential={currentCredential}
                        onCredentialChange={setCurrentCredential}
                        checkedCredential={canCreate ? formCredential : null}
                        checksLocked={!configUnlocked}
                        checksLockedReason={gateMessage ?? undefined}
                        onChecksPassedChange={onChecksPassedChange}
                      />
                    )}

                    {(!noCredentials || hasVisibleBoundFields) && (
                      <Divider paddingParallel={0} paddingPerpendicular={0} />
                    )}

                    {/* The wizard could not reach these sections without a
                      valid credential; on one page they stay locked, under one
                      Disabled that blocks pointer and keyboard, until the
                      credential and the bound fields are valid and the
                      capability checks pass. */}
                    <Disabled
                      disabled={!formUnlocked}
                      tooltip={formLockReason}
                      data-testid="connector-form"
                    >
                      <Section gap={6} alignItems="stretch" width="full">
                        <ConnectorContentSection
                          config={credentialBoundFields.rest}
                          values={formikProps.values}
                          connector={connector}
                          currentCredential={formCredential}
                          disabled={!formUnlocked}
                        />

                        <Divider paddingParallel={0} paddingPerpendicular={0} />
                        <ConnectorSettingsSection
                          connector={connector}
                          currentCredential={formCredential}
                          disabled={!formUnlocked}
                        />

                        {connector !== "file" && (
                          <>
                            <Divider
                              paddingParallel={0}
                              paddingPerpendicular={0}
                            />
                            <ScheduleSection
                              defaultPruneFreqHours={defaultPruneFreqHours}
                              disabled={!formUnlocked}
                            />
                          </>
                        )}
                      </Section>
                    </Disabled>
                  </Section>
                </>
              )}
            </SettingsLayouts.Body>
          </SettingsLayouts.Root>
        );
      }}
    </Formik>
  );
}

export interface AddConnectorWrapperProps {
  connector: ConfigurableSources;
}

export default function AddConnectorWrapper({
  connector,
}: AddConnectorWrapperProps) {
  const t = useTranslations("admin.connectorsList");
  const router = useRouter();
  const searchParams = useSearchParams();
  const mode = searchParams?.get("mode"); // 'federated' or 'regular'

  useToastFromQuery({
    oauth_failed: {
      message: t("oauthFailed.toast"),
      type: "error",
    },
  });

  if (!isValidSource(connector)) {
    return (
      <SettingsLayouts.Root width="sm">
        <SettingsLayouts.Header
          icon={SvgAlertCircle}
          title={t("invalidConnector.title", { connector })}
        />
        <SettingsLayouts.Body>
          <div className="me-auto">
            <Button onClick={() => router.push("/admin/indexing-status")}>
              {t("invalidConnector.homeButton.label")}
            </Button>
          </div>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  const sourceMetadata = getSourceMetadata(connector);
  const supportsFederated = sourceMetadata.federated === true;

  // Only show federated form if explicitly requested via URL parameter
  const showFederatedForm = mode === "federated" && supportsFederated;

  if (showFederatedForm) {
    return (
      <div className="flex justify-center w-full h-full">
        <div className="mt-12 w-full max-w-4xl mx-auto">
          <FederatedConnectorForm connector={connector} />
        </div>
      </div>
    );
  }

  return <AddConnectorForm connector={connector} />;
}
