"use client";

import { useCallback, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { Route } from "next";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import { Formik, Form } from "formik";
import {
  SvgCpu,
  SvgExternalLink,
  SvgLock,
  SvgMoon,
  SvgSliders,
  SvgSun,
  SvgTrash,
} from "@opal/icons";
import Card from "@/refresh-components/cards/Card";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Button from "@/refresh-components/buttons/Button";
import Switch from "@/refresh-components/inputs/Switch";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { useUser } from "@/components/user/UserProvider";
import { useTheme } from "next-themes";
import { ThemePreference } from "@/lib/types";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import { usePopup } from "@/components/admin/connectors/Popup";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import { deleteAllChatSessions } from "@/app/chat/services/lib";
import { useAuthType, useLlmManager } from "@/lib/hooks";
import { AuthType } from "@/lib/constants";
import PATManagement from "@/components/user/PATManagement";
import { useFederatedOAuthStatus } from "@/lib/hooks/useFederatedOAuthStatus";
import { useCCPairs } from "@/lib/hooks/useCCPairs";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import Separator from "@/refresh-components/Separator";
import Text from "@/refresh-components/texts/Text";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";

function GeneralSettings() {
  const { user, updateUserPersonalization, updateUserThemePreference } =
    useUser();
  const { theme, setTheme } = useTheme();
  const { popup, setPopup } = usePopup();
  const router = useRouter();
  const pathname = usePathname();
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);

  const {
    personalizationValues,
    updatePersonalizationField,
    handleSavePersonalization,
    isSavingPersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onSuccess: () =>
      setPopup({
        message: "Personalization updated successfully",
        type: "success",
      }),
    onError: () =>
      setPopup({
        message: "Failed to update personalization",
        type: "error",
      }),
  });

  const handleDeleteAllChats = useCallback(async () => {
    setIsDeleting(true);
    try {
      const response = await deleteAllChatSessions();
      if (response.ok) {
        setPopup({
          message: "All your chat sessions have been deleted.",
          type: "success",
        });
        if (pathname.includes("/chat")) {
          router.push("/chat");
        }
      } else {
        throw new Error("Failed to delete all chat sessions");
      }
    } catch (error) {
      setPopup({
        message: "Failed to delete all chat sessions",
        type: "error",
      });
    } finally {
      setIsDeleting(false);
      setShowDeleteConfirmation(false);
    }
  }, [pathname, router, setPopup]);

  return (
    <>
      {popup}

      {showDeleteConfirmation && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete All Chats"
          submit={
            <Button
              danger
              onClick={() => {
                void handleDeleteAllChats();
              }}
              disabled={isDeleting}
            >
              {isDeleting ? "Deleting..." : "Delete"}
            </Button>
          }
        >
          <GeneralLayouts.Section gap={0.5}>
            <Text>
              All your chat sessions and history will be permanently deleted.
              Deletion cannot be undone.
            </Text>
            <Text>Are you sure you want to delete all chats?</Text>
          </GeneralLayouts.Section>
        </ConfirmationModalLayout>
      )}

      <GeneralLayouts.Section gap={2}>
        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Profile" />
          <Card>
            <InputLayouts.Horizontal
              label="Full Name"
              description="We'll display this name in the app."
            >
              <InputTypeIn
                placeholder="Your name"
                value={personalizationValues.name}
                onChange={(e) =>
                  updatePersonalizationField("name", e.target.value)
                }
              />
            </InputLayouts.Horizontal>
            <InputLayouts.Horizontal
              label="Work Role"
              description="Share your role to better tailor responses."
            >
              <InputTypeIn
                placeholder="Your role"
                value={personalizationValues.role}
                onChange={(e) =>
                  updatePersonalizationField("role", e.target.value)
                }
              />
            </InputLayouts.Horizontal>
            <div className="flex justify-end">
              <Button
                onClick={() => {
                  void handleSavePersonalization();
                }}
                disabled={
                  isSavingPersonalization ||
                  personalizationValues.name.length === 0
                }
              >
                {isSavingPersonalization ? "Saving..." : "Save"}
              </Button>
            </div>
          </Card>
        </GeneralLayouts.Section>

        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Appearance" />
          <Card>
            <InputLayouts.Horizontal
              label="Color Mode"
              description="Select your preferred color mode for the UI."
            >
              <InputSelect
                value={theme}
                onValueChange={(value) => {
                  setTheme(value);
                  updateUserThemePreference(value as ThemePreference);
                }}
              >
                <InputSelect.Trigger />
                <InputSelect.Content>
                  <InputSelect.Item
                    value={ThemePreference.SYSTEM}
                    icon={SvgCpu}
                  >
                    System
                  </InputSelect.Item>
                  <InputSelect.Item value={ThemePreference.LIGHT} icon={SvgSun}>
                    Light
                  </InputSelect.Item>
                  <InputSelect.Item value={ThemePreference.DARK} icon={SvgMoon}>
                    Dark
                  </InputSelect.Item>
                </InputSelect.Content>
              </InputSelect>
            </InputLayouts.Horizontal>
          </Card>
        </GeneralLayouts.Section>

        <Separator noPadding />

        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Danger Zone" />
          <Card>
            <InputLayouts.Horizontal
              label="Delete All Chats"
              description="Permanently delete all your chat sessions."
            >
              <Button
                danger
                onClick={() => setShowDeleteConfirmation(true)}
                leftIcon={SvgTrash}
              >
                Delete All Chats
              </Button>
            </InputLayouts.Horizontal>
          </Card>
        </GeneralLayouts.Section>
      </GeneralLayouts.Section>
    </>
  );
}

function ChatPreferencesSettings() {
  const {
    user,
    updateUserTemperatureOverrideEnabled,
    updateUserPersonalization,
    updateUserAutoScroll,
    updateUserShortcuts,
  } = useUser();
  const { popup, setPopup } = usePopup();
  const llmManager = useLlmManager();

  const {
    personalizationValues,
    toggleUseMemories,
    updateMemoryAtIndex,
    addMemory,
    handleSavePersonalization,
    isSavingPersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onSuccess: () =>
      setPopup({
        message: "Personalization updated successfully",
        type: "success",
      }),
    onError: () =>
      setPopup({
        message: "Failed to update personalization",
        type: "error",
      }),
  });

  return (
    <>
      {popup}

      <GeneralLayouts.Section gap={2}>
        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Chats" />
          <Card>
            <InputLayouts.Horizontal
              label="Default Model"
              description="This model will be used by Onyx by default in your chats."
            >
              <LLMPopover
                llmManager={llmManager}
                // onSelect={(selected) => {
                //   if (selected === null) {
                //     void handleChangeDefaultModel(null);
                //   } else {
                //     const { modelName, provider, name } =
                //       parseLlmDescriptor(selected);
                //     if (modelName && name) {
                //       void handleChangeDefaultModel(
                //         structureValue(name, provider, modelName)
                //       );
                //     }
                //   }
                // }}
              />
            </InputLayouts.Horizontal>

            <InputLayouts.Horizontal
              label="Chat Auto-scroll"
              description="Automatically scroll to new content as chat generates response."
            >
              <Switch
                checked={user?.preferences.auto_scroll}
                onCheckedChange={(checked) => {
                  updateUserAutoScroll(checked);
                }}
              />
            </InputLayouts.Horizontal>

            <InputLayouts.Horizontal
              label="Temperature override"
              description="Set the temperature for the LLM"
            >
              <Switch
                checked={user?.preferences.temperature_override_enabled}
                onCheckedChange={(checked) => {
                  updateUserTemperatureOverrideEnabled(checked);
                }}
              />
            </InputLayouts.Horizontal>
          </Card>
        </GeneralLayouts.Section>

        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Prompt Shortcuts" />
          <Card>
            <InputLayouts.Horizontal
              label="Use Prompt Shortcuts"
              description="Enable shortcuts to quickly insert common prompts."
            >
              <Switch
                checked={user?.preferences?.shortcut_enabled}
                onCheckedChange={(checked) => {
                  updateUserShortcuts(checked);
                }}
              />
            </InputLayouts.Horizontal>
          </Card>
        </GeneralLayouts.Section>

        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Personalization" />
          <Card>
            <InputLayouts.Horizontal
              label="Reference Stored Memories"
              description="Let Onyx reference stored memories in chats."
            >
              <Switch
                checked={personalizationValues.use_memories}
                onCheckedChange={(checked) => toggleUseMemories(checked)}
              />
            </InputLayouts.Horizontal>

            <div className="space-y-3">
              {personalizationValues.memories.map((memory, index) => (
                <InputTextArea
                  key={index}
                  value={memory}
                  placeholder="Write something Onyx should remember"
                  onChange={(event) =>
                    updateMemoryAtIndex(index, event.target.value)
                  }
                />
              ))}
              <Button tertiary onClick={addMemory} className="w-full">
                Add Memory
              </Button>
            </div>
          </Card>
        </GeneralLayouts.Section>
      </GeneralLayouts.Section>
    </>
  );
}

function AccountsAccessSettings() {
  const { user } = useUser();
  const { popup, setPopup } = usePopup();
  const authType = useAuthType();
  const [showPasswordModal, setShowPasswordModal] = useState(false);

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = authType && authType !== AuthType.DISABLED;

  const handleChangePassword = useCallback(
    async (values: {
      currentPassword: string;
      newPassword: string;
      confirmPassword: string;
    }) => {
      if (values.newPassword !== values.confirmPassword) {
        setPopup({ message: "New passwords do not match", type: "error" });
        return;
      }

      try {
        const response = await fetch("/api/password/change-password", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            old_password: values.currentPassword,
            new_password: values.newPassword,
          }),
        });

        if (response.ok) {
          setPopup({
            message: "Password changed successfully",
            type: "success",
          });
          setShowPasswordModal(false);
        } else {
          const errorData = await response.json();
          setPopup({
            message: errorData.detail || "Failed to change password",
            type: "error",
          });
        }
      } catch (error) {
        setPopup({
          message: "An error occurred while changing the password",
          type: "error",
        });
      }
    },
    [setPopup]
  );

  if (!showPasswordSection && !showTokensSection) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-muted-foreground">
          No account settings available.
        </p>
      </div>
    );
  }

  return (
    <>
      {popup}

      {showPasswordModal && (
        <Formik
          initialValues={{
            currentPassword: "",
            newPassword: "",
            confirmPassword: "",
          }}
          onSubmit={async (values, { setSubmitting }) => {
            await handleChangePassword(values);
            setSubmitting(false);
          }}
        >
          {({ values, handleChange, isSubmitting, dirty }) => (
            <Form>
              <ConfirmationModalLayout
                icon={SvgLock}
                title="Change Password"
                submit={
                  <Button
                    type="submit"
                    disabled={
                      isSubmitting ||
                      !dirty ||
                      !values.currentPassword ||
                      !values.newPassword ||
                      !values.confirmPassword
                    }
                  >
                    {isSubmitting ? "Updating..." : "Update"}
                  </Button>
                }
                onClose={() => {
                  setShowPasswordModal(false);
                }}
              >
                <GeneralLayouts.Section gap={1}>
                  <InputLayouts.Vertical label="Current Password">
                    <InputTypeIn
                      name="currentPassword"
                      type="password"
                      value={values.currentPassword}
                      onChange={handleChange}
                    />
                  </InputLayouts.Vertical>
                  <InputLayouts.Vertical label="New Password">
                    <InputTypeIn
                      name="newPassword"
                      type="password"
                      value={values.newPassword}
                      onChange={handleChange}
                    />
                  </InputLayouts.Vertical>
                  <InputLayouts.Vertical label="Confirm New Password">
                    <InputTypeIn
                      name="confirmPassword"
                      type="password"
                      value={values.confirmPassword}
                      onChange={handleChange}
                    />
                  </InputLayouts.Vertical>
                </GeneralLayouts.Section>
              </ConfirmationModalLayout>
            </Form>
          )}
        </Formik>
      )}

      <GeneralLayouts.Section gap={2}>
        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Accounts" />
          <Card>
            <InputLayouts.Horizontal
              label="Email"
              description="Your account email address."
            >
              <Text>{user?.email ?? "anonymous"}</Text>
            </InputLayouts.Horizontal>

            {showPasswordSection && (
              <InputLayouts.Horizontal
                label="Password"
                description="Update your account password."
              >
                <Button
                  secondary
                  leftIcon={SvgLock}
                  onClick={() => setShowPasswordModal(true)}
                >
                  Change Password
                </Button>
              </InputLayouts.Horizontal>
            )}
          </Card>
        </GeneralLayouts.Section>

        {showTokensSection && (
          <GeneralLayouts.Section gap={0.75}>
            <InputLayouts.Label label="Access Tokens" />
            <Card>
              <h2 className="text-xl font-bold mb-4">Personal Access Tokens</h2>
              <p className="text-sm text-text-03 mb-4">
                Create tokens to authenticate API requests. Tokens inherit all
                your permissions.
              </p>
              <PATManagement />
            </Card>
          </GeneralLayouts.Section>
        )}
      </GeneralLayouts.Section>
    </>
  );
}

function ConnectorsSettings() {
  const { popup, setPopup } = usePopup();
  const router = useRouter();
  const [isDisconnecting, setIsDisconnecting] = useState<number | null>(null);

  const {
    connectors: federatedConnectors,
    refetch: refetchFederatedConnectors,
    loading: isFederatedLoading,
  } = useFederatedOAuthStatus();

  const { ccPairs, isLoading: isCCPairsLoading } = useCCPairs();

  const hasConnectors =
    (ccPairs && ccPairs.length > 0) ||
    (federatedConnectors && federatedConnectors.length > 0);

  const isLoadingConnectors = isCCPairsLoading || isFederatedLoading;

  const handleConnectOAuth = useCallback(
    (authorizeUrl: string) => {
      router.push(authorizeUrl as Route);
    },
    [router]
  );

  const handleDisconnectOAuth = useCallback(
    async (connectorId: number) => {
      setIsDisconnecting(connectorId);
      try {
        const response = await fetch(`/api/federated/${connectorId}/oauth`, {
          method: "DELETE",
        });

        if (response.ok) {
          setPopup({
            message: "Disconnected successfully",
            type: "success",
          });
          if (refetchFederatedConnectors) {
            refetchFederatedConnectors();
          }
        } else {
          throw new Error("Failed to disconnect");
        }
      } catch (error) {
        setPopup({
          message: "Failed to disconnect",
          type: "error",
        });
      } finally {
        setIsDisconnecting(null);
      }
    },
    [refetchFederatedConnectors, setPopup]
  );

  const formatSourceName = (source: string) => {
    return source
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  };

  if (isLoadingConnectors) {
    return (
      <div className="flex items-center justify-center py-8">
        <SimpleLoader />
      </div>
    );
  }

  return (
    <>
      {popup}
      <GeneralLayouts.Section gap={2}>
        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Data Sources" />
          <Card>
            <div>
              <h3 className="text-lg font-medium mb-4">Connected Services</h3>
              <p className="text-sm text-muted-foreground mb-4">
                Manage your connected services to search across all your
                content.
              </p>

              {/* Indexed Connectors Section */}
              {ccPairs && ccPairs.length > 0 && (
                <div className="space-y-3 mb-6">
                  <h4 className="text-md font-medium text-muted-foreground">
                    Indexed Connectors
                  </h4>
                  {(() => {
                    const groupedConnectors = ccPairs.reduce(
                      (acc, ccPair) => {
                        const source = ccPair.source;
                        if (!acc[source]) {
                          acc[source] = {
                            source,
                            count: 0,
                            hasSuccessfulRun: false,
                          };
                        }
                        acc[source]!.count++;
                        if (ccPair.has_successful_run) {
                          acc[source]!.hasSuccessfulRun = true;
                        }
                        return acc;
                      },
                      {} as Record<
                        string,
                        {
                          source: ValidSources;
                          count: number;
                          hasSuccessfulRun: boolean;
                        }
                      >
                    );

                    return Object.values(groupedConnectors).map((group) => (
                      <div
                        key={group.source}
                        className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30"
                      >
                        <div className="flex items-center gap-3">
                          <SourceIcon sourceType={group.source} iconSize={24} />
                          <div>
                            <p className="font-medium">
                              {formatSourceName(group.source)}
                            </p>
                            <p className="text-sm text-muted-foreground">
                              {group.count > 1
                                ? `${group.count} connectors`
                                : "Connected"}
                            </p>
                          </div>
                        </div>
                        <div className="text-sm text-muted-foreground font-medium">
                          Active
                        </div>
                      </div>
                    ));
                  })()}
                </div>
              )}

              {/* Federated Search Section */}
              {federatedConnectors && federatedConnectors.length > 0 && (
                <div className="space-y-3">
                  <h4 className="text-md font-medium text-muted-foreground">
                    Federated Connectors
                  </h4>
                  {federatedConnectors.map((connector) => {
                    const sourceMetadata = getSourceMetadata(
                      connector.source as ValidSources
                    );
                    return (
                      <div
                        key={connector.federated_connector_id}
                        className="flex items-center justify-between p-4 rounded-lg border border-border"
                      >
                        <div className="flex items-center gap-3">
                          <SourceIcon
                            sourceType={sourceMetadata.internalName}
                            iconSize={24}
                          />
                          <div>
                            <p className="font-medium">
                              {formatSourceName(sourceMetadata.displayName)}
                            </p>
                            <p className="text-sm text-muted-foreground">
                              {connector.has_oauth_token
                                ? "Connected"
                                : "Not connected"}
                            </p>
                          </div>
                        </div>
                        <div>
                          {connector.has_oauth_token ? (
                            <Button
                              secondary
                              onClick={() =>
                                void handleDisconnectOAuth(
                                  connector.federated_connector_id
                                )
                              }
                              disabled={
                                isDisconnecting ===
                                connector.federated_connector_id
                              }
                            >
                              {isDisconnecting ===
                              connector.federated_connector_id
                                ? "Disconnecting..."
                                : "Disconnect"}
                            </Button>
                          ) : (
                            <Button
                              onClick={() => {
                                if (connector.authorize_url) {
                                  handleConnectOAuth(connector.authorize_url);
                                }
                              }}
                              disabled={!connector.authorize_url}
                              leftIcon={SvgExternalLink}
                            >
                              Connect
                            </Button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {!hasConnectors && (
                <div className="text-center py-8">
                  <p className="text-sm text-muted-foreground">
                    No connectors available.
                  </p>
                </div>
              )}
            </div>
          </Card>
        </GeneralLayouts.Section>
      </GeneralLayouts.Section>
    </>
  );
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState(0);
  const { user } = useUser();
  const authType = useAuthType();

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = authType && authType !== AuthType.DISABLED;
  const showAccountsAccessTab = showPasswordSection || showTokensSection;

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={SvgSliders} title="Settings" separator />

      <SettingsLayouts.Body>
        <div className="grid grid-cols-[auto_1fr]">
          {/* Left: Tab Navigation */}
          <div className="flex flex-col px-2 w-[12.5rem]">
            <SidebarTab
              transient={activeTab === 0}
              onClick={() => setActiveTab(0)}
            >
              General
            </SidebarTab>
            <SidebarTab
              transient={activeTab === 1}
              onClick={() => setActiveTab(1)}
            >
              Chat Preferences
            </SidebarTab>
            {showAccountsAccessTab && (
              <SidebarTab
                transient={activeTab === 2}
                onClick={() => setActiveTab(2)}
              >
                Accounts & Access
              </SidebarTab>
            )}
            <SidebarTab
              transient={activeTab === 3}
              onClick={() => setActiveTab(3)}
            >
              Connectors
            </SidebarTab>
          </div>

          {/* Right: Tab Content */}
          <div className="px-4">
            {activeTab === 0 && <GeneralSettings />}
            {activeTab === 1 && <ChatPreferencesSettings />}
            {activeTab === 2 && showAccountsAccessTab && (
              <AccountsAccessSettings />
            )}
            {activeTab === 3 && <ConnectorsSettings />}
          </div>
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
