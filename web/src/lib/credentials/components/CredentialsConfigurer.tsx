"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { mutate } from "swr";
import { Button, Card, Modal, Text } from "@opal/components";
import { ContentAction, Section, toast } from "@opal/layouts";
import { SvgChevronDown, SvgChevronUp, SvgKey } from "@opal/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  EE_ENABLED,
  NEXT_PUBLIC_CLOUD_ENABLED,
  NEXT_PUBLIC_TEST_ENV,
} from "@/lib/constants";
import { deleteCredential } from "@/lib/credential";
import { buildSimilarCredentialInfoURL } from "@/lib/connectors/utils";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/svc";
import { useOAuthDetails } from "@/lib/connectors/hooks";
import type { Credential } from "@/lib/connectors/types";
import CreateCredential from "@/lib/credentials/components/CreateCredential";
import { CreateStdOAuthCredential } from "@/lib/credentials/components/CreateStdOAuthCredential";
import ModifyCredential from "@/lib/credentials/components/ModifyCredential";
import {
  CredentialCreationMethod,
  getCredentialCreationActionLabel,
  getCredentialCreationMethods,
  shouldRedirectToOAuth,
} from "@/lib/credentials/credentialCreation";
import { prepareOAuthAuthorizationRequest } from "@/lib/oauth_utils";
import { useSettings } from "@/lib/settings/hooks";
import { getSourceDisplayName, getSourceMetadata } from "@/lib/sources";
import {
  type AccessType,
  type ConfigurableSources,
  oauthSupportedSources,
} from "@/lib/types";

export interface CredentialsConfigurerProps {
  source: ConfigurableSources;
  /** The connector's access type, forwarded to the credential forms. */
  accessType: AccessType;
  selectedCredential: Credential<any> | null;
  onSelect: (credential: Credential<any>) => void;
}

/**
 * The Credentials card of the create-connector page: pick one of the
 * source's existing credentials, or create one (manually, through OAuth, or
 * through the cloud authorize flow) and pick it.
 */
export function CredentialsConfigurer({
  source,
  accessType,
  selectedCredential,
  onSelect,
}: CredentialsConfigurerProps) {
  const t = useTranslations("admin.connectorsList");
  const tCredentials = useTranslations("admin.credentials");
  const { appName } = useSettings();
  const [open, setOpen] = useState(false);
  const [credentialCreationMethod, setCredentialCreationMethod] =
    useState<CredentialCreationMethod | null>(null);
  const [currentPageUrl, setCurrentPageUrl] = useState<string | null>(null);
  const [isAuthorizing, setIsAuthorizing] = useState(false);
  const [isAuthorizeVisible, setIsAuthorizeVisible] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setCurrentPageUrl(window.location.href);
    }

    if (EE_ENABLED && (NEXT_PUBLIC_CLOUD_ENABLED || NEXT_PUBLIC_TEST_ENV)) {
      const sourceMetadata = getSourceMetadata(source);
      if (sourceMetadata?.oauthSupported == true) {
        setIsAuthorizeVisible(true);
      }
    }
  }, [source]);

  const { data: credentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(source),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );

  const { data: editableCredentials } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(source, true),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );

  const { data: oauthDetails, isLoading: oauthDetailsLoading } =
    useOAuthDetails(source);

  const displayName = getSourceDisplayName(source) || source;
  const credentialCreationMethods = getCredentialCreationMethods(oauthDetails);
  const showExplicitCredentialMethods = credentialCreationMethods.length > 1;

  if (!credentials || !editableCredentials) {
    return null;
  }

  const refresh = () => {
    mutate(buildSimilarCredentialInfoURL(source));
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

  const onSwap = async (credential: Credential<any>) => {
    onSelect(credential);
    toast.success(t("add.credentialSwapped.toast"));
    refresh();
  };

  const closeCredentialModal = () => setCredentialCreationMethod(null);

  const attemptOauthRedirect = async () => {
    try {
      const redirectUrl = await getConnectorOauthRedirectUrl(source, {});
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

  // Gets an auth URL from the server and opens it in a new tab.
  const handleAuthorize = async () => {
    if (!currentPageUrl) return;

    setIsAuthorizing(true);
    try {
      const response = await prepareOAuthAuthorizationRequest(
        source,
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

  const header = (
    <ContentAction
      title={tCredentials("configurer.title")}
      description={tCredentials("configurer.description", { appName })}
      sizePreset="main-content"
      variant="section"
      rightChildren={
        <Button
          icon={open ? SvgChevronUp : SvgChevronDown}
          prominence="tertiary"
          aria-label={
            open
              ? tCredentials("configurer.closeButton.ariaLabel")
              : tCredentials("configurer.openButton.ariaLabel")
          }
          onClick={() => setOpen((current) => !current)}
        />
      }
    />
  );

  if (!open) {
    return (
      <Card border="solid" rounding={4} padding={6}>
        {header}
      </Card>
    );
  }

  return (
    <Card border="solid" rounding={4} padding={6}>
      <Section gap={4} alignItems="start" width="full">
        {header}

        <ModifyCredential
          showIfEmpty
          accessType={accessType}
          defaultedCredential={selectedCredential ?? undefined}
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
              <Button disabled>{t("add.createCredentialButton.label")}</Button>
            ) : (
              credentialCreationMethods.map((method) => (
                <Button
                  key={method}
                  onClick={() => openCredentialCreationMethod(method)}
                >
                  {getCredentialCreationActionLabel(
                    method,
                    displayName,
                    showExplicitCredentialMethods
                  )}
                </Button>
              ))
            )}
            {oauthSupportedSources.includes(source) &&
              (NEXT_PUBLIC_CLOUD_ENABLED || NEXT_PUBLIC_TEST_ENV) && (
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
              )}
          </Section>
        )}

        {credentialCreationMethod !== null && (
          <Modal open onOpenChange={closeCredentialModal}>
            <Modal.Content>
              <Modal.Header
                icon={SvgKey}
                title={t("add.credentialModal.title", { source: displayName })}
                onClose={closeCredentialModal}
              />
              <Modal.Body alignItems="stretch">
                {oauthDetailsLoading ? null : credentialCreationMethod ===
                    CredentialCreationMethod.OAuth && oauthDetails ? (
                  shouldRedirectToOAuth(oauthDetails) ? (
                    <Section alignItems="start">
                      <Text as="p" font="main-ui-body" color="text-03">
                        {t("add.oauthRedirectFailed.message", {
                          source: displayName,
                        })}
                      </Text>
                      <Button onClick={attemptOauthRedirect}>
                        {t("add.retryButton.label")}
                      </Button>
                    </Section>
                  ) : (
                    <CreateStdOAuthCredential
                      sourceType={source}
                      additionalFields={oauthDetails.additional_kwargs}
                    />
                  )
                ) : (
                  <CreateCredential
                    close
                    refresh={refresh}
                    sourceType={source}
                    accessType={accessType}
                    onSwitch={onSwap}
                    onClose={closeCredentialModal}
                  />
                )}
              </Modal.Body>
            </Modal.Content>
          </Modal>
        )}
      </Section>
    </Card>
  );
}
