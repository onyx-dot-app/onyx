"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, SelectCard, Tabs, Text } from "@opal/components";
import { Content, ContentAction, Section, toast } from "@opal/layouts";
// SvgExpand, SvgFold and SvgListTree return with the header buttons below.
import { SvgPlusCircle } from "@opal/icons";
import { CardLoader } from "@opal/loaders";
import type { Credential } from "@/lib/credentials/types";
import { useCredentialSetup } from "@/lib/credentials/hooks";
import { useSettings } from "@/lib/settings/hooks";
import CreateCredential from "@/lib/credentials/components/CreateCredential";
import { CreateStdOAuthCredential } from "@/lib/credentials/components/CreateStdOAuthCredential";
import ModifyCredential from "@/lib/credentials/components/ModifyCredential";
import {
  CredentialCreationMethod,
  shouldRedirectToOAuth,
} from "@/lib/credentials/credentialCreation";
import type { AccessType } from "@/lib/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";

export interface CredentialsConfigurerProps {
  /** The source being set up. */
  connector: ConfigurableSources;
  /** Access type from the connector form; a new credential inherits it. */
  accessType: AccessType;
  /** The credential the page links once the connector is created. */
  currentCredential: Credential<any> | null;
  /** Called when the user picks or creates a credential. */
  onCredentialChange: (credential: Credential<any>) => void;
}

/**
 * The credential step of the connector setup page: pick a saved credential,
 * create one, or authorize the source through OAuth.
 */
export function CredentialsConfigurer({
  connector,
  accessType,
  currentCredential,
  onCredentialChange,
}: CredentialsConfigurerProps) {
  const t = useTranslations("admin.connectorsList");
  const settings = useSettings();
  const {
    displayName,
    credentials,
    error,
    oauthDetails,
    isLoading,
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
        <Section alignItems="start">
          <Button onClick={attemptOauthRedirect}>
            {t("add.authorizeButton.label", { source: displayName })}
          </Button>
        </Section>
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

  // A failed load says so once, not on every retry.
  const failed = error !== undefined;
  useEffect(() => {
    if (failed) toast.error(t("add.credentialsLoadFailed.toast"));
  }, [failed, t]);

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

      {/* The header always shows. Below it: a card loader in the shape of
      the accounts card while the step loads, nothing once loading failed (a
      toast says so), and the accounts and create card once everything
      lands. */}
      {failed ? null : isLoading || !credentials ? (
        <CardLoader border="dashed" color="transparent" />
      ) : (
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
                    value={openMethod ?? defaultMethod}
                    onValueChange={(value) => {
                      // Matched against the real methods rather than cast:
                      // the tab strip hands back a plain string.
                      const picked = methods.find((method) => method === value);
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
            onClick={() => (isCreating ? close() : selectMethod(defaultMethod))}
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
      )}
    </Section>
  );
}
