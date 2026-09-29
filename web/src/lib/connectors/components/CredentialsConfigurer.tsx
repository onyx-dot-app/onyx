"use client";

import { useEffect, useState } from "react";
import useSWR, { mutate } from "swr";
import { useTranslations } from "next-intl";
import { Button, Card, SelectCard, Text } from "@opal/components";
import { Content, ContentAction, Section, toast } from "@opal/layouts";
import { SvgExpand, SvgFold, SvgListTree, SvgPlusCircle } from "@opal/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildSimilarCredentialInfoURL } from "@/lib/connectors/utils";
import type { Credential } from "@/lib/connectors/types";
import { useOAuthDetails } from "@/lib/connectors/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/svc";
import { deleteCredential } from "@/lib/credential";
import CreateCredential from "@/lib/credentials/components/CreateCredential";
import { CreateStdOAuthCredential } from "@/lib/credentials/components/CreateStdOAuthCredential";
import ModifyCredential from "@/lib/credentials/components/ModifyCredential";
import {
  CredentialCreationMethod,
  getCredentialCreationMethods,
  shouldRedirectToOAuth,
} from "@/lib/credentials/credentialCreation";
import { getSourceDisplayName, getSourceMetadata } from "@/lib/sources";
import { prepareOAuthAuthorizationRequest } from "@/lib/oauth_utils";
import {
  EE_ENABLED,
  NEXT_PUBLIC_CLOUD_ENABLED,
  NEXT_PUBLIC_TEST_ENV,
} from "@/lib/constants";
import {
  oauthSupportedSources,
  type AccessType,
  type ConfigurableSources,
} from "@/lib/types";

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

  const [credentialCreationMethod, setCredentialCreationMethod] =
    useState<CredentialCreationMethod | null>(null);
  // Wiring only: the fold button has no handler yet.
  const [isOpen] = useState(true);
  const [currentPageUrl, setCurrentPageUrl] = useState<string | null>(null);
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

  const displayName = getSourceDisplayName(connector) || connector;
  // A source with one way in says what the card makes; a source with two
  // names each way instead, so the two cards stay distinguishable.
  const newAccountLabel = t("add.newAccountButton.label", {
    source: displayName,
  });
  const showAuthorize =
    oauthSupportedSources.includes(connector) &&
    (NEXT_PUBLIC_CLOUD_ENABLED || NEXT_PUBLIC_TEST_ENV);
  const credentialCreationMethods = getCredentialCreationMethods(oauthDetails);
  const showExplicitCredentialMethods = credentialCreationMethods.length > 1;

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
    onCredentialChange(selectedCredential);
    toast.success(t("add.credentialSwapped.toast"));
    refresh();
  };

  const closeCredentialForm = () => setCredentialCreationMethod(null);

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
        onClose={closeCredentialForm}
      />
    );
  }

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

  // Gets an auth url from the server and sends the user to it in a popup.
  const handleAuthorize = async () => {
    if (!currentPageUrl) return;

    setIsAuthorizing(true);
    try {
      const response = await prepareOAuthAuthorizationRequest(
        connector,
        currentPageUrl,
        t("add.oauthStartFailed.toast")
      );
      if (response.url) {
        window.open(response.url, "_blank", "noopener,noreferrer");
      } else {
        toast.error(t("add.oauthUrlFailed.toast"));
      }
    } catch (error: unknown) {
      if (error instanceof Error) {
        toast.error(t("add.error.toast", { detail: error.message }));
      } else {
        toast.error(t("add.unknownError.toast"));
      }
    } finally {
      setIsAuthorizing(false);
    }
  };

  if (!credentials || !editableCredentials) {
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
        rightChildren={
          <>
            <Button icon={SvgListTree} prominence="tertiary">
              {t("add.savedAccountsButton.label", {
                count: credentials.length,
              })}
            </Button>
            <Button
              icon={isOpen ? SvgFold : SvgExpand}
              prominence="tertiary"
              aria-label={
                isOpen
                  ? t("add.collapseButton.ariaLabel")
                  : t("add.expandButton.ariaLabel")
              }
            />
          </>
        }
      />

      <Card border="solid" rounding={4} padding={6}>
        <Section gap={4} alignItems="start" width="full">
          <ModifyCredential
            showIfEmpty
            accessType={accessType}
            defaultedCredential={currentCredential!}
            credentials={credentials}
            editableCredentials={editableCredentials}
            onDeleteCredential={onDeleteCredential}
            onSwitch={onSwap}
          />

          {showAuthorize && (
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
                hidden={!isAuthorizeVisible}
              >
                {isAuthorizing
                  ? t("add.authorizeButton.pendingLabel")
                  : t("add.authorizeButton.label", { source: displayName })}
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
      {oauthDetailsLoading ? (
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
        credentialCreationMethods.map((method) => {
          const open = credentialCreationMethod === method;
          return (
            <SelectCard
              key={method}
              expandable
              expanded={open}
              expandableContentHeight="full"
              border="solid"
              state={open ? "filled" : "empty"}
              rounding={4}
              padding={2}
              expandedContent={
                <div className="p-4">{renderCredentialForm(method)}</div>
              }
              onClick={() =>
                open
                  ? closeCredentialForm()
                  : openCredentialCreationMethod(method)
              }
            >
              <Section padding={2} width="full">
                <Content
                  icon={SvgPlusCircle}
                  title={newAccountLabel}
                  sizePreset="main-ui"
                  variant="body"
                  color={open ? "interactive" : "muted"}
                />
              </Section>
            </SelectCard>
          );
        })
      )}
    </Section>
  );
}
