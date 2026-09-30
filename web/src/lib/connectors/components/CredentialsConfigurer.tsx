"use client";

import { useTranslations } from "next-intl";
import { Button, Card, SelectCard, Text } from "@opal/components";
import { Content, ContentAction, Section, toast } from "@opal/layouts";
// SvgExpand, SvgFold and SvgListTree return with the header buttons below.
import { SvgPlusCircle } from "@opal/icons";
import type { Credential } from "@/lib/connectors/types";
import { useCredentialSetup } from "@/lib/connectors/hooks";
import { useSettings } from "@/lib/settings/hooks";
import CreateCredential from "@/lib/credentials/components/CreateCredential";
import { CreateStdOAuthCredential } from "@/lib/credentials/components/CreateStdOAuthCredential";
import ModifyCredential from "@/lib/credentials/components/ModifyCredential";
import {
  CredentialCreationMethod,
  shouldRedirectToOAuth,
} from "@/lib/credentials/credentialCreation";
import type { AccessType, ConfigurableSources } from "@/lib/types";

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
    oauthDetails,
    isLoading,
    methods,
    canAuthorize,
    openMethod,
    open,
    close,
    remove,
    refresh,
    authorize,
    isAuthorizing,
  } = useCredentialSetup(connector);

  // A source with one way in says what the card makes; a source with two
  // names each way instead, so the two cards stay distinguishable.
  const newAccountLabel = t("add.newAccountButton.label", {
    source: displayName,
  });
  async function onDeleteCredential(credential: Credential<any | null>) {
    const error = await remove(credential);
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
   * The creation form for one method, rendered inside that method's card.
   * The OAuth branch only reaches its redirect message if the details
   * changed under us: `openCredentialCreationMethod` redirects instead of
   * opening the card when a redirect is all the source needs.
   */
  function renderCredentialForm(method: CredentialCreationMethod) {
    if (method === CredentialCreationMethod.OAuth && oauthDetails) {
      return shouldRedirectToOAuth(oauthDetails) ? (
        <Section alignItems="start">
          <Text as="p" font="main-ui-body" color="text-03">
            {t("add.oauthRedirectFailed.message", { source: displayName })}
          </Text>
          <Button onClick={attemptOauthRedirect}>
            {t("add.retryButton.label")}
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

  async function openCredentialCreationMethod(
    method: CredentialCreationMethod
  ) {
    const error = await open(method);
    if (error !== null) {
      toast.error(error || t("add.oauthStartFailed.toast"));
    }
  }

  // Gets an auth url from the server and sends the user to it in a popup.
  async function handleAuthorize() {
    const error = await authorize(t("add.oauthStartFailed.toast"));
    if (error !== null) {
      toast.error(error || t("add.unknownError.toast"));
    }
  }

  if (!credentials) {
    return null;
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

        {/* One card per way of creating a credential. The fold button is the
      only control: the card around it is a plain container, so a click in
      the open form cannot fold it away. While the OAuth details are still
      loading we do not yet know how many cards there are, so a single
      disabled one holds the place. */}
        {isLoading ? (
          <Card
            border="solid"
            color="transparent"
            rounding={4}
            padding={4}
            disabled
          >
            <ContentAction
              icon={SvgPlusCircle}
              title={newAccountLabel}
              sizePreset="main-ui"
              variant="section"
              padding={0}
            />
          </Card>
        ) : (
          methods.map((method) => {
            const isExpanded = openMethod === method;
            return (
              <SelectCard
                key={method}
                expandable
                expanded={isExpanded}
                expandableContentHeight="full"
                border="solid"
                state={isExpanded ? "filled" : "empty"}
                rounding={4}
                padding={2}
                expandedContent={
                  <div className="p-4">{renderCredentialForm(method)}</div>
                }
                onClick={() =>
                  isExpanded ? close() : openCredentialCreationMethod(method)
                }
              >
                <Section padding={2} width="full">
                  <Content
                    icon={SvgPlusCircle}
                    title={newAccountLabel}
                    sizePreset="main-ui"
                    variant="body"
                    color={isExpanded ? "interactive" : "muted"}
                  />
                </Section>
              </SelectCard>
            );
          })
        )}
      </Section>
    </Section>
  );
}
