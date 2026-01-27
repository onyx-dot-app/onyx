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
import { deleteCredential } from "@/lib/credential";
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
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { createBuildConnector } from "@/app/build/v1/configure/utils/createBuildConnector";
import { useUser } from "@/components/user/UserProvider";

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
  isSingleStep?: boolean;
  onConnectorSuccess?: () => void;
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
  const { user } = useUser();

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

  const handleConnect = async () => {
    if (!selectedCredential || !isSingleStep) return;

    setIsConnecting(true);

    try {
      const result = await createBuildConnector({
        connectorType,
        credential: selectedCredential,
        userEmail: user?.email,
      });

      if (!result.success) {
        throw new Error(result.error);
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
            onCredentialCreated={async (credential) => {
              onSelectCredential(credential);
              // For single-step connectors (like Gmail), create connector immediately
              // For multi-step connectors, continue to config step
              if (isSingleStep && onConnectorSuccess) {
                // Create connector immediately for single-step flow
                setIsConnecting(true);
                try {
                  const result = await createBuildConnector({
                    connectorType,
                    credential: credential,
                    userEmail: user?.email,
                  });

                  if (!result.success) {
                    throw new Error(result.error);
                  }

                  onConnectorSuccess();
                } catch (err) {
                  setPopup?.({
                    message:
                      err instanceof Error
                        ? err.message
                        : "Failed to create connector",
                    type: "error",
                  });
                } finally {
                  setIsConnecting(false);
                }
              } else {
                onContinue();
              }
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
