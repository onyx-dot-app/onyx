"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { useFormikContext } from "formik";
import { Disabled } from "@opal/core";
import { Button, Card, SelectCard, Tabs, Text } from "@opal/components";
import { Content, ContentAction, Section, toast } from "@opal/layouts";
// SvgExpand, SvgFold and SvgListTree return with the header buttons below.
import { SvgPlusCircle } from "@opal/icons";
import type { Credential } from "@/lib/credentials/types";
import { useCredentialSetup } from "@/lib/credentials/hooks";
import { useSettings } from "@/lib/settings/hooks";
import CreateCredential from "@/lib/credentials/components/CreateCredential";
import { OAuthSignInRow } from "@/lib/credentials/components/OAuthSignInRow";
import { CreateStdOAuthCredential } from "@/lib/credentials/components/CreateStdOAuthCredential";
import ModifyCredential from "@/lib/credentials/components/ModifyCredential";
import { shouldRedirectToOAuth } from "@/lib/credentials/utils";
import { CredentialCreationMethod } from "@/lib/credentials/types";
import type { AccessType } from "@/lib/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import type { ConnectionConfiguration } from "@/lib/connectors/types";
import { useConnectorConfiguration } from "@/lib/connectors/connectors";
import { toWireAccess } from "@/lib/connectors/accessType";
import {
  useDraftCheckRun,
  type UseDraftCheckRunResult,
} from "@/lib/connectors/checks/hooks";
import { connectorFormState } from "@/lib/connectors/checks/formState";
import type {
  CapabilityCheckResult,
  CapabilityCheckStatus,
  DraftCheckState,
} from "@/lib/connectors/checks/types";
import ConnectorsCheckCard from "@/views/admin/connectors/AddConnectorPage/components/ConnectorsCheckCard";
import ConnectorsCheckPromptCard from "@/views/admin/connectors/AddConnectorPage/components/ConnectorsCheckPromptCard";

const FINISHED_STATES: ReadonlySet<string> = new Set<CapabilityCheckStatus>([
  "passed",
  "failed",
  "indeterminate",
  "skipped",
]);

/** A check that has an outcome. Not-applicable checks never get one. */
function isFinished(
  check: DraftCheckState
): check is DraftCheckState & { state: CapabilityCheckStatus } {
  return FINISHED_STATES.has(check.state);
}

function toCheckResult(
  check: DraftCheckState & { state: CapabilityCheckStatus }
): CapabilityCheckResult {
  return {
    capability: check.capability,
    check_id: check.check_id,
    display_name: check.display_name,
    required: check.required,
    status: check.state,
    message: check.message,
    remediation: check.remediation,
    docs_link: check.docs_link,
    duration_ms: check.duration_ms,
  };
}

interface AuthenticationAccountSectionProps {
  /** The source being set up. */
  connector: ConfigurableSources;
  /** Access type from the connector form; a new credential inherits it. */
  accessType: AccessType;
  /** The credential the page links once the connector is created. */
  currentCredential: Credential<any> | null;
  /** Called when the user picks or creates a credential. */
  onCredentialChange: (credential: Credential<any>) => void;
  /** The credential the capability checks run with; `null` hides them. */
  checkedCredential: Credential<any> | null;
  /** Locks the Start Checks prompt, as the configuration below is locked. */
  checksLocked: boolean;
  /** Why the prompt is locked, for its tooltip. */
  checksLockedReason?: string;
}

/**
 * The credential step of the connector setup page: pick a saved credential,
 * create one, or authorize the source through OAuth. Once a credential is
 * picked, its capability checks run against the unsaved form below it.
 */
export default function AuthenticationAccountSection({
  connector,
  accessType,
  currentCredential,
  onCredentialChange,
  checkedCredential,
  checksLocked,
  checksLockedReason,
}: AuthenticationAccountSectionProps) {
  const t = useTranslations("admin.connectorsList");
  const settings = useSettings();
  const { values } = useFormikContext<Record<string, unknown>>();
  const configuration: ConnectionConfiguration =
    useConnectorConfiguration(connector);
  const formState: Record<string, unknown> = useMemo(
    () => connectorFormState(configuration, values),
    [configuration, values]
  );
  const checkRun: UseDraftCheckRunResult = useDraftCheckRun({
    source: connector,
    credentialId: checkedCredential?.id ?? null,
    accessType: toWireAccess(accessType, {
      restrict_access_to_groups: values.restrict_access_to_groups === true,
      restriction_group_ids: Array.isArray(values.restriction_group_ids)
        ? values.restriction_group_ids.filter(
            (id): id is number => typeof id === "number"
          )
        : [],
    }).access_type,
    formState,
  });
  const checks: DraftCheckState[] = checkRun.snapshot?.checks ?? [];
  const {
    displayName,
    credentials,
    oauthDetails,
    methods,
    canAuthorize,
    openMethod,
    namesMethods,
    open,
    selectMethod,
    close,
    remove,
    refresh,
    authorize,
    isAuthorizing,
  } = useCredentialSetup(connector);

  // The create card's one label, whatever the number of routes; the tabs
  // inside it name the routes.
  const newAccountLabel = t("add.newAccountButton.label", {
    source: displayName,
  });
  async function onDeleteCredential(credential: Credential<any | null>) {
    const error = await remove(credential, t("add.unknownError.toast"));
    if (error === null) {
      toast.success(t("add.credentialDeleted.toast"));
    } else {
      toast.error(error);
    }
  }

  async function onSwap(selectedCredential: Credential<any>) {
    onCredentialChange(selectedCredential);
    toast.success(t("add.credentialSwapped.toast"));
    refresh();
  }

  /**
   * One route into the source, rendered inside the card. A source that
   * takes no extra OAuth fields is a plain hand-off, so its route is the
   * button alone.
   */
  function renderCredentialForm(method: CredentialCreationMethod) {
    if (method === CredentialCreationMethod.OAuth && oauthDetails) {
      return shouldRedirectToOAuth(oauthDetails) ? (
        <OAuthSignInRow source={displayName} onConnect={attemptOauthRedirect} />
      ) : (
        <CreateStdOAuthCredential
          sourceType={connector}
          additionalFields={oauthDetails.additional_kwargs}
        />
      );
    }
    return (
      <CreateCredential
        close
        refresh={refresh}
        sourceType={connector}
        accessType={accessType}
        onSwitch={onSwap}
        onClose={close}
      />
    );
  }

  async function attemptOauthRedirect() {
    const error = await open(CredentialCreationMethod.OAuth);
    if (error !== null) {
      toast.error(error || t("add.oauthStartFailed.toast"));
    }
  }

  /** The card is open while a route is chosen; the route is the open tab. */
  const isCreating = openMethod !== null;

  /** The route the card opens on: typing one in, when the source allows it. */
  const defaultMethod =
    methods.find((method) => method === CredentialCreationMethod.Manual) ??
    methods[0] ??
    CredentialCreationMethod.Manual;

  /**
   * The routes in tab order. Typing a token in leads, because it is the
   * route every source shares and the one the card opens on;
   * `getCredentialCreationMethods` returns OAuth first and is shared with
   * the connector detail page, so the order is settled here rather than
   * there.
   */
  const orderedMethods = [...methods].sort((left) =>
    left === CredentialCreationMethod.Manual ? -1 : 1
  );

  // Gets an auth url from the server and sends the user to it in a popup.
  async function handleAuthorize() {
    const error = await authorize(t("add.oauthStartFailed.toast"));
    if (error !== null) {
      toast.error(error || t("add.unknownError.toast"));
    }
  }

  return (
    <Section gap={4} alignItems="stretch" width="full">
      <ContentAction
        title={t("add.credentialStep.title")}
        description={t("add.credentialStep.description", {
          appName: settings.appName,
        })}
        sizePreset="main-content"
        variant="section"
        padding={0}
        // The saved-accounts count has nowhere to lead yet, and the fold
        // button only ever closes, so it reads as broken while no card is
        // open. Both wait for the rest of the accounts panel.
        // rightChildren={
        //   <>
        //     <Button icon={SvgListTree} prominence="tertiary">
        //       {t("add.savedAccountsButton.label", {
        //         count: credentials.length,
        //       })}
        //     </Button>
        //     <Button
        //       icon={isOpen ? SvgFold : SvgExpand}
        //       prominence="tertiary"
        //       aria-label={
        //         isOpen
        //           ? t("add.collapseButton.ariaLabel")
        //           : t("add.expandButton.ariaLabel")
        //       }
        //       onClick={close}
        //     />
        //   </>
        // }
      />

      {/* The page mounts this step only once the credentials have loaded,
      and shows its own loader and error until then; the guard only keeps
      the types honest. */}
      {!credentials ? null : (
        <Section gap={6} alignItems="stretch" width="full">
          <Section gap={4} alignItems="stretch" width="full">
            <Card border="solid" rounding={4} padding={6}>
              <Section gap={4} alignItems="start" width="full">
                <ModifyCredential
                  showIfEmpty
                  accessType={accessType}
                  defaultedCredential={currentCredential!}
                  credentials={credentials}
                  onDeleteCredential={onDeleteCredential}
                  onSwitch={onSwap}
                />

                {canAuthorize && (
                  <Section
                    flexDirection="row"
                    justifyContent="start"
                    gap={1}
                    className="mt-6"
                  >
                    <Button
                      disabled={isAuthorizing}
                      variant="action"
                      onClick={handleAuthorize}
                    >
                      {isAuthorizing
                        ? t("add.authorizeButton.pendingLabel")
                        : t("add.authorizeButton.label", {
                            source: displayName,
                          })}
                    </Button>
                  </Section>
                )}
              </Section>
            </Card>

            {/* One card creates a credential. Its header toggles it; the fold
          below is a plain container, so a click in the open form cannot fold
          it away. The routes into the source are tabs inside the fold. */}
            <SelectCard
              expandable
              expanded={isCreating}
              expandableContentHeight="full"
              border="solid"
              state={isCreating ? "filled" : "empty"}
              rounding={4}
              padding={2}
              // The card is one action, so it names itself. Nothing inside the
              // interactive half is focusable, so a role here folds no other
              // control into that name.
              role="button"
              aria-label={newAccountLabel}
              tabIndex={0}
              expandedContent={
                <div className="p-4" data-testid="credential-form">
                  {namesMethods ? (
                    <Tabs
                      gap={4}
                      value={openMethod ?? defaultMethod}
                      onValueChange={(value) => {
                        // Matched against the real methods rather than cast:
                        // the tab strip hands back a plain string.
                        const picked = methods.find(
                          (method) => method === value
                        );
                        if (picked) selectMethod(picked);
                      }}
                    >
                      <Tabs.List>
                        {orderedMethods.map((method) => (
                          <Tabs.Trigger key={method} value={method}>
                            {method === CredentialCreationMethod.OAuth
                              ? t("add.connectWithTab.label")
                              : t("add.manualTab.label")}
                          </Tabs.Trigger>
                        ))}
                      </Tabs.List>
                      {/* A tab switch keeps what the user typed in the other
                      route. */}
                      {orderedMethods.map((method) => (
                        <Tabs.Content key={method} value={method} keepMounted>
                          {renderCredentialForm(method)}
                        </Tabs.Content>
                      ))}
                    </Tabs>
                  ) : (
                    renderCredentialForm(defaultMethod)
                  )}
                </div>
              }
              onClick={() =>
                isCreating ? close() : selectMethod(defaultMethod)
              }
            >
              <Section padding={2} width="full">
                <Content
                  icon={SvgPlusCircle}
                  title={newAccountLabel}
                  sizePreset="main-ui"
                  variant="body"
                  color={isCreating ? "interactive" : "muted"}
                />
              </Section>
            </SelectCard>
          </Section>

          {/* The checks run only on request: a prompt holds their place until
          the user starts them, or after a start request fails. */}
          {checkRun.started && checkedCredential && !checkRun.error ? (
            <ConnectorsCheckCard
              results={checks.flatMap((check) =>
                isFinished(check) ? [toCheckResult(check)] : []
              )}
              inProgressCount={
                checks.filter(
                  (check) =>
                    check.state === "pending" || check.state === "running"
                ).length
              }
              expectedCount={
                checks.filter((check) => check.state === "waiting").length
              }
              running={checkRun.running}
              onRerun={checkRun.rerun}
            />
          ) : (
            <Disabled disabled={checksLocked} tooltip={checksLockedReason}>
              <ConnectorsCheckPromptCard
                disabled={checksLocked}
                onStart={checkRun.begin}
              />
            </Disabled>
          )}
        </Section>
      )}
    </Section>
  );
}
