"use client";

import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { Formik, getIn } from "formik";
import * as Yup from "yup";
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
import {
  createConnectorWithCredential,
  credentialPairMetadata,
} from "@/lib/credentials/svc";
import { submitFiles, submitGoogleSite } from "@/lib/connectors/svc";
import {
  useBindingGateMessage,
  type UseBoundFieldsGateResult,
} from "@/lib/connectors/hooks";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import {
  getCredentialSpec,
  isDraftCredential,
  realmFields,
  toCredentialRef,
  toCredentialRequest,
} from "@/lib/credentials/utils";
import AccountRealmFields from "@/views/admin/connectors/AddConnectorPage/form/AccountRealmFields";
import type {
  Credential,
  CredentialRef,
  DraftCredential,
} from "@/lib/credentials/types";
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
  useCredentialFieldCopy,
  useGmailCredentials,
  useCredentialLoad,
  useGoogleDriveCredentials,
  useResetSavedDraftCredential,
  useSavedDraftCredential,
} from "@/lib/credentials/hooks";
import {
  NEW_ACCOUNT_FIELD,
  initialNewAccountValues,
  newAccountSchema,
  typedAccountSpec,
  typedDraft,
} from "@/views/admin/connectors/AddConnectorPage/newAccount";
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
import {
  useConnectorChecks,
  useResetConnectorChecks,
} from "@/lib/connectors/checks/hooks";

const BASE_CONNECTOR_URL = "/api/manage/admin/connector";
const CONNECTOR_CREATION_TIMEOUT_MS = 10000; // ~10 seconds is reasonable for longer connector validation

interface ConnectorChecksGates {
  /** The checks that validate the credential passed: the form may unlock. */
  formUnlocked: boolean;
  /** Every required check passed for the current form: Create may run. */
  createReady: boolean;
}

interface ConnectorChecksGateProps {
  source: ConfigurableSources;
  credential: CredentialRef | null;
  children: (gates: ConnectorChecksGates) => ReactNode;
}

/**
 * Gives the form the capability checks' two gates. The hook needs the Formik
 * context, which the form's render function sits inside but cannot call hooks
 * in.
 */
function ConnectorChecksGate({
  source,
  credential,
  children,
}: ConnectorChecksGateProps) {
  const { formUnlocked, createReady } = useConnectorChecks({
    source,
    credential,
  });
  return children({ formUnlocked, createReady });
}

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

  // The picked saved account. Clicking a saved card picks it; typing into
  // the new account drops the pick (see AuthenticationAccountSection).
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
  // Form keys that are not connector config: tab controls, and the typed
  // account, which Create sends as the credential.
  const formControlFieldNames = new Set([
    ...[...configuration.values, ...configuration.advanced_values]
      .filter((field) => field.type === "tab")
      .map((field) => field.name),
    NEW_ACCOUNT_FIELD,
  ]);

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

  // Sources without a credential spec skip the credential section.
  const noCredentials = credentialSpec == null;

  // The new account is part of this form: its fields live under
  // NEW_ACCOUNT_FIELD and validate with the rest while it is chosen.
  const tValidation = useTranslations("admin.credentials.validation");
  const fieldCopy = useCredentialFieldCopy(connector);
  const typedSpec = typedAccountSpec(connector);
  // Where the typed account works, asked for above the account section.
  const accountRealmFields = typedSpec ? realmFields(typedSpec) : [];
  const accountSchema = typedSpec
    ? newAccountSchema(typedSpec, {
        fieldTitle: (key) => fieldCopy(key).title,
        required: (field) => tValidation("required", { field }),
        empty: (field) => tValidation("empty", { field }),
        invalidEmail: (field) => tValidation("invalidEmail", { field }),
        fileRequired: (field) => tValidation("fileRequired", { field }),
        authMethodRequired: tValidation("authMethodRequired"),
      })
    : null;

  /**
   * The chosen account for these form values: the saved pick; else the typed
   * one when its values are valid (or Google's live account).
   */
  const accountFor = (
    values: Record<string, unknown>
  ): Credential<any> | DraftCredential | null =>
    currentCredential ||
    typedDraft(connector, accountSchema, getIn(values, NEW_ACCOUNT_FIELD)) ||
    liveGDriveCredential ||
    liveGmailCredential ||
    null;

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
  // The rest of the form also waits for the capability checks. Each visit
  // starts without a run. Sources without a credential step have no checks.
  useResetConnectorChecks(connector);
  // A check run saves a typed account as a draft; Create names that draft.
  useResetSavedDraftCredential(connector);
  const { savedDraft } = useSavedDraftCredential(connector);
  const checksT = useTranslations("admin.connectorChecks");

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

  const initialValues: ReturnType<typeof createConnectorInitialValues> =
    createConnectorInitialValues(connector);
  if (typedSpec) {
    initialValues[NEW_ACCOUNT_FIELD] = initialNewAccountValues(typedSpec);
  }

  return (
    <Formik
      initialValues={initialValues}
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
      ).shape({
        // With a saved pick, the typed account is not used, so it must not
        // block Create. With no pick it is the only account, and its errors
        // show.
        [NEW_ACCOUNT_FIELD]:
          accountSchema && !currentCredential ? accountSchema : Yup.mixed(),
      })}
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

          const connectorData: ConnectorBase<any> = {
            connector_specific_config: transformedConnectorSpecificConfig,
            input_type: isLoadState(connector) ? "load_state" : "poll", // single case
            name: name,
            source: connector,
            access_type: access_type,
            refresh_freq: advancedConfiguration.refreshFreq || null,
            prune_freq: advancedConfiguration.pruneFreq || null,
            indexing_start: advancedConfiguration.indexingStart || null,
            groups: groups,
          };
          const connectorCreationPromise = (async () => {
            const credential = noCredentials ? null : accountFor(values);
            if (!credential) {
              const { errorDetail, isSuccess, response } =
                await submitConnector<any>(connectorData, undefined, true);

              // Store the connector id immediately for potential timeout
              if (response?.id) {
                connectorIdRef.current = response.id;
              }
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

            // With credential: one request creates the connector and pairs
            // it, saving a typed account on the way.
            const credentialRef = toCredentialRef(credential);
            if (credentialRef) {
              const createResponse = await createConnectorWithCredential({
                connector: connectorData,
                pairing: credentialPairMetadata(
                  name,
                  access_type,
                  groups,
                  auto_sync_options,
                  undefined,
                  access_type === SYNC_RESTRICTED_ACCESS_TYPE
                    ? wireAccess.restriction_group_ids
                    : dataAccess,
                  manageAccess
                ),
                credential: toCredentialRequest(credentialRef, savedDraft),
                credentialSharing: isDraftCredential(credential)
                  ? credential.sharing
                  : undefined,
              });
              if (createResponse.ok) {
                onSuccess();
              } else if (!timeoutErrorHappenedRef.current) {
                // Only show error if timeout didn't happen
                const errorData = await createResponse.json();
                toast.error(errorData.detail || errorData.message);
              }
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
        const formCredential = accountFor(formikProps.values);
        const canCreate = noCredentials || formCredential !== null;
        const newAccountReady =
          typedDraft(
            connector,
            accountSchema,
            getIn(formikProps.values, NEW_ACCOUNT_FIELD)
          ) !== null;
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
        const checkedCredential = canCreate ? formCredential : null;
        return (
          <ConnectorChecksGate
            source={connector}
            credential={toCredentialRef(checkedCredential)}
          >
            {(checks) => {
              const formUnlocked: boolean =
                configUnlocked && (noCredentials || checks.formUnlocked);
              // Non-required checks never block Create.
              const createReady: boolean =
                formUnlocked && (noCredentials || checks.createReady);
              const formLockReason: string | undefined = !configUnlocked
                ? (gateMessage ?? undefined)
                : formUnlocked
                  ? undefined
                  : checksT("lockReason");
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
                          !createReady ||
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
                          description={t(
                            "add.credentialsLoadFailed.description"
                          )}
                        />
                      </PageCenter>
                    ) : (
                      <>
                        <BoundFieldsGate
                          source={connector}
                          credential={
                            noCredentials
                              ? null
                              : toCredentialRef(formCredential)
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
                                advancedFields={
                                  credentialBoundFields.advancedValues
                                }
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

                          {accountRealmFields.length > 0 && (
                            <>
                              <AccountRealmFields
                                source={connector}
                                fields={accountRealmFields}
                                savedCredential={
                                  formCredential &&
                                  !isDraftCredential(formCredential)
                                    ? formCredential
                                    : null
                                }
                              />
                              <Divider
                                paddingParallel={0}
                                paddingPerpendicular={0}
                              />
                            </>
                          )}

                          {!noCredentials && (
                            <AuthenticationAccountSection
                              connector={connector}
                              accessType={formikProps.values.access_type}
                              currentCredential={currentCredential}
                              onCredentialChange={setCurrentCredential}
                              newAccountReady={newAccountReady}
                              checkedCredential={checkedCredential}
                              // A typed account's binding waits for a run,
                              // so the checks stay open for it.
                              checksLocked={
                                !configUnlocked &&
                                gate?.reason?.kind !== "runChecks"
                              }
                            />
                          )}

                          {(!noCredentials || hasVisibleBoundFields) && (
                            <Divider
                              paddingParallel={0}
                              paddingPerpendicular={0}
                            />
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

                              <Divider
                                paddingParallel={0}
                                paddingPerpendicular={0}
                              />
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
                                    defaultPruneFreqHours={
                                      defaultPruneFreqHours
                                    }
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
          </ConnectorChecksGate>
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
