"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Divider,
  Fold,
  SelectButton,
  SelectCard,
  Tabs,
} from "@opal/components";
import { Content, ContentAction, Section, toast } from "@opal/layouts";
import { SvgListTree, SvgPlusCircle } from "@opal/icons";
import type { Credential, DraftCredential } from "@/lib/credentials/types";
import {
  useCredentialCheckReports,
  useCredentialSetup,
} from "@/lib/credentials/hooks";
import { useSettings } from "@/lib/settings/hooks";
import CreateCredential from "@/lib/credentials/components/CreateCredential";
import { CredentialFieldsRenderer } from "@/lib/credentials/components/CredentialFieldsRenderer";
import { ShareAccountField } from "@/lib/credentials/components/ShareAccountField";
import { getIn, useFormikContext } from "formik";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import {
  NEW_ACCOUNT_FIELD,
  typedAccountSpec,
  type NewAccountValues,
} from "@/views/admin/connectors/AddConnectorPage/newAccount";
import { OAuthSignInRow } from "@/lib/credentials/components/OAuthSignInRow";
import { CreateStdOAuthCredential } from "@/lib/credentials/components/CreateStdOAuthCredential";
import {
  shouldRedirectToOAuth,
  toCredentialRef,
} from "@/lib/credentials/utils";
import { CredentialCreationMethod } from "@/lib/credentials/types";
import type { AccessType } from "@/lib/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import AuthenticationAccountCard from "@/views/admin/connectors/AddConnectorPage/components/AuthenticationAccountCard";
import CredentialChecksCard from "@/views/admin/connectors/AddConnectorPage/components/CredentialChecksCard";

interface AuthenticationAccountSectionProps {
  /** The source being set up. */
  connector: ConfigurableSources;
  /** Access type from the connector form; a new credential inherits it. */
  accessType: AccessType;
  /** The saved account the page pairs once the connector is created. */
  currentCredential: Credential<any> | null;
  /** Called when the user picks a saved account, or drops it. */
  onCredentialChange: (credential: Credential<any> | null) => void;
  /**
   * Whether the account typed into the new-account form has valid values. It
   * is then the chosen account, masking any saved pick; Create saves it.
   */
  newAccountReady: boolean;
  /** The account the capability checks run with; `null` locks them. */
  checkedCredential: Credential<any> | DraftCredential | null;
  /** Locks the Start Checks prompt, as the configuration below is locked. */
  checksLocked: boolean;
}

/**
 * The credential step of the connector setup page: pick a saved credential,
 * create one, or authorize the source through OAuth. Once the credential
 * section is valid, the user can run the capability checks against the
 * unsaved form; the rest of the form unlocks when they pass.
 */
export default function AuthenticationAccountSection({
  connector,
  accessType,
  currentCredential,
  onCredentialChange,
  newAccountReady,
  checkedCredential,
  checksLocked,
}: AuthenticationAccountSectionProps) {
  const t = useTranslations("admin.connectorsList");
  const settings = useSettings();
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
  const checkReports = useCredentialCheckReports(connector);
  const [showSavedAccounts, setShowSavedAccounts] = useState<boolean>(true);

  // The create card's one label, whatever the number of routes; the tabs
  // inside it name the routes.
  const newAccountLabel = t("add.newAccountButton.label", {
    source: displayName,
  });
  // A saved pick shows as chosen unless a valid typed account masks it.
  const selectedSavedId: number | null = newAccountReady
    ? null
    : (currentCredential?.id ?? null);
  // The source's fields when a new account is typed into this form; `null`
  // when it saves through its own account form instead.
  const typedSpec = typedAccountSpec(connector);
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const { values } = useFormikContext<Record<string, unknown>>();
  const newAccountValues: NewAccountValues | undefined = getIn(
    values,
    NEW_ACCOUNT_FIELD
  );

  async function onDeleteCredential(credential: Credential<any | null>) {
    const error = await remove(credential, t("add.unknownError.toast"));
    if (error === null) {
      // A deleted account cannot stay picked.
      if (credential.id === selectedSavedId) onCredentialChange(null);
    } else {
      toast.error(error);
    }
  }

  async function onSwap(selectedCredential: Credential<any>) {
    onCredentialChange(selectedCredential);
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
    if (typedSpec) {
      // Part of the connector form, and saved only by Create. Once its
      // values are valid it is the chosen account.
      return (
        <Section alignItems="stretch" gap={4}>
          <CredentialFieldsRenderer
            source={connector}
            spec={typedSpec}
            namePrefix={NEW_ACCOUNT_FIELD}
            authMethod={
              typeof newAccountValues?.authentication_method === "string"
                ? newAccountValues.authentication_method
                : undefined
            }
          />
          {businessTier && (
            <>
              <Divider paddingParallel={0} paddingPerpendicular={0} />
              <ShareAccountField
                namePrefix={NEW_ACCOUNT_FIELD}
                disabled={!newAccountReady}
              />
            </>
          )}
        </Section>
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
    <Section gap={2} alignItems="stretch" width="full">
      <ContentAction
        title={t("add.credentialStep.title")}
        description={t("add.credentialStep.description", {
          appName: settings.appName,
        })}
        sizePreset="main-content"
        variant="section"
        padding={0}
        rightChildren={
          <SelectButton
            icon={SvgListTree}
            variant="select-heavy"
            // Blue while an account is picked; held in its hover look
            // while the list is open.
            state={
              selectedSavedId === null
                ? "empty"
                : showSavedAccounts
                  ? "selected"
                  : "filled"
            }
            interaction={showSavedAccounts ? "hover" : "rest"}
            aria-expanded={showSavedAccounts}
            onClick={() => setShowSavedAccounts((shown) => !shown)}
          >
            {t("add.savedAccountsButton.label", {
              count: credentials?.length ?? 0,
            })}
          </SelectButton>
        }
      />

      {/* The page mounts this step only once the credentials have loaded,
      and shows its own loader and error until then; the guard only keeps
      the types honest. */}
      {!credentials ? null : (
        <Section gap={6} alignItems="stretch" width="full">
          <Section gap={0} alignItems="stretch" width="full" height="fit">
            {/* Hidden accounts animate away, then leave the page. The fold
            holds the cards' gap, so a closed one leaves no space behind. A
            div, as Section's own padding would override the bottom one. */}
            <Fold open={showSavedAccounts && credentials.length > 0}>
              <div className="flex flex-col gap-2 pb-2">
                {credentials.map((credential) => (
                  <AuthenticationAccountCard
                    key={credential.id}
                    credential={credential}
                    source={connector}
                    sourceName={displayName}
                    selected={credential.id === selectedSavedId}
                    onSelect={() => onSwap(credential)}
                    onDeselect={() => onCredentialChange(null)}
                    onDelete={() => onDeleteCredential(credential)}
                    checkReport={checkReports.reportFor(credential.id)}
                    onRerunChecks={() => checkReports.rerun(credential.id)}
                  />
                ))}
              </div>
            </Fold>
            <Section gap={2} alignItems="stretch" width="full">
              {canAuthorize && (
                <Section flexDirection="row" justifyContent="start" gap={1}>
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

              {/* One card creates a credential. Its header toggles it; the fold
          below is a plain container, so a click in the open form cannot fold
          it away. The routes into the source are tabs inside the fold. */}
              <SelectCard
                expandable
                expanded={isCreating}
                expandableContentHeight="full"
                // The form keeps what was typed while folded, and a valid
                // typed account stays the chosen one.
                expandableKeepMounted
                border="solid"
                // Selected while its valid values make it the chosen account.
                state={
                  newAccountReady ? "selected" : isCreating ? "filled" : "empty"
                }
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
          </Section>

          <CredentialChecksCard
            source={connector}
            credential={toCredentialRef(checkedCredential)}
            locked={checksLocked || !checkedCredential}
          />
        </Section>
      )}
    </Section>
  );
}
