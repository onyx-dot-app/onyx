"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import Button from "@/refresh-components/buttons/Button";
import Modal from "@/refresh-components/Modal";
import { SvgKey } from "@opal/icons";
import {
  ConfigurableSources,
  ValidSources,
  oauthSupportedSources,
} from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import { getSourceDisplayName } from "@/lib/sources";
import {
  useOAuthDetails,
  getConnectorOauthRedirectUrl,
} from "@/lib/connectors/oauth";
import { deleteCredential, linkCredential } from "@/lib/credential";
import ModifyCredential from "@/components/credentials/actions/ModifyCredential";
import CreateCredential from "@/components/credentials/actions/CreateCredential";
import { CreateStdOAuthCredential } from "@/components/credentials/actions/CreateStdOAuthCredential";
import { GmailMain } from "@/app/admin/connectors/[connector]/pages/gmail/GmailPage";
import CardSection from "@/components/admin/CardSection";
import { Spinner } from "@/components/Spinner";
import {
  NEXT_PUBLIC_CLOUD_ENABLED,
  NEXT_PUBLIC_TEST_ENV,
} from "@/lib/constants";
import { BUILD_MODE_OAUTH_COOKIE_NAME } from "@/app/build/v1/constants";
import Cookies from "js-cookie";
import { createConnector } from "@/lib/connector";
import { connectorConfigs, isLoadState } from "@/lib/connectors/connectors";
import { PopupSpec } from "@/components/admin/connectors/Popup";

interface CredentialStepProps {
  connectorType: ValidSources;
  credentials: Credential<any>[];
  selectedCredential: Credential<any> | null;
  onSelectCredential: (cred: Credential<any>) => void;
  onCredentialCreated: (cred: Credential<any>) => void;
  onCredentialDeleted: (credId: number) => void;
  onContinue: () => void;
  onOAuthRedirect: () => void;
  refresh?: () => void;
  /** When true, this is a single-step flow - connect button creates the connector directly */
  isSingleStep?: boolean;
  /** Callback when connector is successfully created (for single-step flow) */
  onConnectorSuccess?: () => void;
  /** Popup setter for error messages */
  setPopup?: (popup: PopupSpec | null) => void;
}

export default function CredentialStep({
  connectorType,
  credentials,
  selectedCredential,
  onSelectCredential,
  onCredentialCreated,
  onCredentialDeleted,
  onContinue,
  onOAuthRedirect,
  refresh = () => {},
  isSingleStep = false,
  onConnectorSuccess,
  setPopup,
}: CredentialStepProps) {
  const [createCredentialFormToggle, setCreateCredentialFormToggle] =
    useState(false);
  const [isAuthorizing, setIsAuthorizing] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);

  const { data: oauthDetails, isLoading: oauthDetailsLoading } =
    useOAuthDetails(connectorType);

  const isAuthorizeVisible =
    oauthDetails?.oauth_enabled !== true ||
    (oauthDetails?.additional_kwargs?.length ?? 0) === 0;

  const handleAuthorize = async () => {
    setIsAuthorizing(true);
    onOAuthRedirect();

    const redirectUrl = await getConnectorOauthRedirectUrl(connectorType, {
      desired_return_url: `${window.location.origin}/build/v1/configure`,
    });
    if (redirectUrl) {
      window.location.href = redirectUrl;
    } else {
      setIsAuthorizing(false);
      console.error("Failed to get OAuth redirect URL");
    }
  };

  /**
   * For single-step connectors, directly create the connector with default values
   */
  const handleConnect = async () => {
    if (!selectedCredential || !isSingleStep) return;

    setIsConnecting(true);

    try {
      const config =
        connectorConfigs[connectorType as keyof typeof connectorConfigs];
      const connectorName = `build-mode-${connectorType}`;

      // Create connector with empty/default config (single-step connectors don't need config)
      const [connectorError, connector] = await createConnector({
        name: connectorName,
        source: connectorType,
        input_type: isLoadState(connectorType) ? "load_state" : "poll",
        connector_specific_config: {},
        refresh_freq: config?.overrideDefaultFreq || 1800, // 30 minutes default
        prune_freq: 2592000, // 30 days default
        indexing_start: null,
        access_type: "private",
      });

      if (connectorError || !connector) {
        throw new Error(connectorError || "Failed to create connector");
      }

      // Link credential to connector with file_system processing mode
      const linkResponse = await linkCredential(
        connector.id,
        selectedCredential.id,
        connectorName,
        "private",
        [], // No groups for build mode connectors
        undefined, // No auto sync options
        "file_system" // Use file system processing mode for build connectors
      );

      if (!linkResponse.ok) {
        const linkError = await linkResponse.json();
        throw new Error(linkError.detail || "Failed to link credential");
      }

      onConnectorSuccess?.();
    } catch (err) {
      setPopup?.({
        message:
          err instanceof Error ? err.message : "Failed to create connector",
        type: "error",
      });
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDeleteCredential = async (credential: Credential<any>) => {
    try {
      const response = await deleteCredential(credential.id);
      if (response.ok) {
        onCredentialDeleted(credential.id);
      } else {
        console.error("Failed to delete credential");
      }
    } catch (error) {
      console.error("Error deleting credential:", error);
    }
  };

  const handleSwap = (newCredential: Credential<any>) => {
    onSelectCredential(newCredential);
  };

  const hasCredentials = credentials.length > 0;

  return (
    <Section flexDirection="column" alignItems="center" height="fit">
      <CardSection>
        {connectorType === ValidSources.Gmail ? (
          <GmailMain
            buildMode
            onOAuthRedirect={onOAuthRedirect}
            onCredentialCreated={(credential) => {
              onSelectCredential(credential);
              onContinue();
            }}
          />
        ) : (
          <>
            <ModifyCredential
              showIfEmpty
              accessType="public"
              defaultedCredential={selectedCredential!}
              credentials={credentials}
              editableCredentials={credentials}
              onDeleteCredential={handleDeleteCredential}
              onSwitch={handleSwap}
            />
            {!createCredentialFormToggle && (
              <div className="mt-6 flex gap-4 justify-between items-center">
                <div className="flex gap-4">
                  <Button
                    onClick={async () => {
                      if (oauthDetails && oauthDetails.oauth_enabled) {
                        if (oauthDetails.additional_kwargs.length > 0) {
                          setCreateCredentialFormToggle(true);
                        } else {
                          const redirectUrl =
                            await getConnectorOauthRedirectUrl(connectorType, {
                              desired_return_url: `${window.location.origin}/build/v1/configure`,
                            });
                          if (redirectUrl) {
                            onOAuthRedirect();
                            window.location.href = redirectUrl;
                          } else {
                            setCreateCredentialFormToggle(
                              (createConnectorToggle) => !createConnectorToggle
                            );
                          }
                        }
                      } else {
                        // For Google Drive, set build mode flag for OAuth redirect
                        if (connectorType === ValidSources.GoogleDrive) {
                          Cookies.set(BUILD_MODE_OAUTH_COOKIE_NAME, "true", {
                            path: "/",
                          });
                          onOAuthRedirect();
                        }
                        setCreateCredentialFormToggle(
                          (createConnectorToggle) => !createConnectorToggle
                        );
                      }
                    }}
                  >
                    Create New
                  </Button>
                  {oauthSupportedSources.includes(
                    connectorType as ConfigurableSources
                  ) &&
                    (NEXT_PUBLIC_CLOUD_ENABLED || NEXT_PUBLIC_TEST_ENV) && (
                      <Button
                        action
                        onClick={handleAuthorize}
                        disabled={isAuthorizing}
                        hidden={!isAuthorizeVisible}
                      >
                        {isAuthorizing
                          ? "Authorizing..."
                          : `Authorize with ${getSourceDisplayName(
                              connectorType
                            )}`}
                      </Button>
                    )}
                </div>
                {hasCredentials && (
                  <Button
                    primary
                    onClick={isSingleStep ? handleConnect : onContinue}
                    disabled={!selectedCredential || isConnecting}
                  >
                    {isSingleStep
                      ? isConnecting
                        ? "Connecting..."
                        : "Connect"
                      : "Continue"}
                  </Button>
                )}
              </div>
            )}

            {createCredentialFormToggle && (
              <Modal
                open
                onOpenChange={() => setCreateCredentialFormToggle(false)}
              >
                <Modal.Content width="md" height="fit">
                  <Modal.Header
                    icon={SvgKey}
                    title={`Create a ${getSourceDisplayName(
                      connectorType
                    )} credential`}
                    onClose={() => setCreateCredentialFormToggle(false)}
                  />
                  <Modal.Body>
                    {oauthDetailsLoading ? (
                      <Spinner />
                    ) : (
                      <>
                        {oauthDetails && oauthDetails.oauth_enabled ? (
                          <CreateStdOAuthCredential
                            sourceType={connectorType}
                            additionalFields={oauthDetails.additional_kwargs}
                          />
                        ) : (
                          <CreateCredential
                            close
                            refresh={refresh}
                            sourceType={connectorType}
                            accessType="public"
                            setPopup={() => {}}
                            onSwitch={async (cred) => {
                              onCredentialCreated(cred);
                              setCreateCredentialFormToggle(false);
                            }}
                            onClose={() => setCreateCredentialFormToggle(false)}
                          />
                        )}
                      </>
                    )}
                  </Modal.Body>
                </Modal.Content>
              </Modal>
            )}
          </>
        )}
      </CardSection>
    </Section>
  );
}
