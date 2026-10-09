"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Button, Divider, SelectCard, Tabs } from "@opal/components";
import { Content, Section, toast } from "@opal/layouts";
import { SvgPlusCircle } from "@opal/icons";
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
  credentialMatchesRealm,
  realmFields,
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
   * Whether the account typed into the new-account form has valid values.
   * Without a saved pick it is then the chosen account; Create saves it.
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

  // The create card's one label, whatever the number of routes; the tabs
  // inside it name the routes.
  const newAccountLabel = t("add.newAccountButton.label", {
    source: displayName,
  });
  const selectedSavedId: number | null = currentCredential?.id ?? null;
  // The source's fields when a new account is typed into this form; `null`
  // when it saves through its own account form instead.
  const typedSpec = typedAccountSpec(connector);
  const accountRealmFields = typedSpec ? realmFields(typedSpec) : [];
  const realmKeys: ReadonlySet<string> = new Set(
    accountRealmFields.map(([key]) => key)
  );
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const { values } = useFormikContext<Record<string, unknown>>();
  const newAccountValues: NewAccountValues | undefined = getIn(
    values,
    NEW_ACCOUNT_FIELD
  );

  // The realm, filled in first above, restricts the saved accounts to the
  // ones that work there.
  const realmValues: Record<string, unknown> = newAccountValues ?? {};
  const isSelectable = (credential: Credential<any>): boolean =>
    credentialMatchesRealm(
      accountRealmFields,
      credential.credential_json ?? {},
      realmValues
    );
  const pickOutsideRealm: boolean =
    currentCredential !== null && !isSelectable(currentCredential);
  useEffect(() => {
    if (pickOutsideRealm) onCredentialChange(null);
  }, [pickOutsideRealm, onCredentialChange]);

  // Typing into the new account chooses it: the saved pick is dropped. The
  // realm is not part of it, as it applies to saved accounts too.
  const newAccountKey: string = JSON.stringify(
    Object.entries(newAccountValues ?? {}).filter(
      ([key]) => !realmKeys.has(key)
    )
  );
  const lastNewAccountKey = useRef<string>(newAccountKey);
  useEffect(() => {
    if (newAccountKey === lastNewAccountKey.current) return;
    lastNewAccountKey.current = newAccountKey;
    if (currentCredential !== null) onCredentialChange(null);
  }, [newAccountKey, currentCredential, onCredentialChange]);

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
    // The typed values stay: typing into them again chooses the new account.
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
            // Asked for above this section, first.
            exclude={realmKeys}
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
      <Content
        title={t("add.credentialStep.title")}
        description={t("add.credentialStep.description", {
          appName: settings.appName,
        })}
        sizePreset="main-content"
        variant="section"
      />

      {/* The page mounts this step only once the credentials have loaded,
      and shows its own loader and error until then; the guard only keeps
      the types honest. */}
      {!credentials ? null : (
        <Section gap={6} alignItems="stretch" width="full">
          <Section gap={2} alignItems="stretch" width="full" height="fit">
            {credentials.map((credential) => (
              <AuthenticationAccountCard
                key={credential.id}
                credential={credential}
                source={connector}
                sourceName={displayName}
                selected={credential.id === selectedSavedId}
                selectable={isSelectable(credential)}
                onSelect={() => onSwap(credential)}
                onDeselect={() => onCredentialChange(null)}
                onDelete={() => onDeleteCredential(credential)}
                checkReport={checkReports.reportFor(credential.id)}
                onRerunChecks={() => checkReports.rerun(credential.id)}
              />
            ))}
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
                // The form keeps what was typed while folded.
                expandableKeepMounted
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
