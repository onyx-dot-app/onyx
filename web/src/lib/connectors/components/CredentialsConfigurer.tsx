"use client";

import { useEffect, useState } from "react";
import useSWR, { mutate } from "swr";
import { useTranslations } from "next-intl";
import { Button, Card, Modal, Text } from "@opal/components";
import { Content, Section, toast } from "@opal/layouts";
import { SvgKey } from "@opal/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildSimilarCredentialInfoURL } from "@/lib/connectors/utils";
import type { Credential } from "@/lib/connectors/types";
import { useOAuthDetails } from "@/lib/connectors/hooks";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/svc";
import { deleteCredential } from "@/lib/credential";
import CreateCredential from "@/lib/credentials/components/CreateCredential";
import { CreateStdOAuthCredential } from "@/lib/credentials/components/CreateStdOAuthCredential";
import ModifyCredential from "@/lib/credentials/components/ModifyCredential";
import {
  CredentialCreationMethod,
  getCredentialCreationActionLabel,
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

  const closeCredentialModal = () => setCredentialCreationMethod(null);

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
    <Card border="solid" rounding={4} padding={6}>
      <Section gap={4} alignItems="start" width="full">
        <Content
          title={t("add.credentialStep.title")}
          sizePreset="main-content"
          variant="section"
        />

        <ModifyCredential
          showIfEmpty
          accessType={accessType}
          defaultedCredential={currentCredential!}
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
            {oauthSupportedSources.includes(connector) &&
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
                      sourceType={connector}
                      additionalFields={oauthDetails.additional_kwargs}
                    />
                  )
                ) : (
                  <CreateCredential
                    close
                    refresh={refresh}
                    sourceType={connector}
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
