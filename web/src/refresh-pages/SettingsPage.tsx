"use client";

import { useCallback, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { Route } from "next";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import {
  SvgCpu,
  SvgExternalLink,
  SvgMoon,
  SvgSliders,
  SvgSun,
  SvgTrash,
} from "@opal/icons";
import Card from "@/refresh-components/Card";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import LineItem from "@/refresh-components/buttons/LineItem";
import Button from "@/refresh-components/buttons/Button";
import Switch from "@/refresh-components/inputs/Switch";
import { SubLabel } from "@/components/Field";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { useUser } from "@/components/user/UserProvider";
import { useTheme } from "next-themes";
import { ThemePreference } from "@/lib/types";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";
import LLMSelector from "@/components/llm/LLMSelector";
import { parseLlmDescriptor, structureValue } from "@/lib/llm/utils";
import { setUserDefaultModel } from "@/lib/userSettings";
import { deleteAllChatSessions } from "@/app/chat/services/lib";
import { useAuthType } from "@/lib/hooks";
import { AuthType } from "@/lib/constants";
import PATManagement from "@/components/user/PATManagement";
import { useFederatedOAuthStatus } from "@/lib/hooks/useFederatedOAuthStatus";
import { useCCPairs } from "@/lib/hooks/useCCPairs";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";

function GeneralSettings() {
  const {
    user,
    updateUserAutoScroll,
    updateUserShortcuts,
    updateUserTemperatureOverrideEnabled,
    updateUserPersonalization,
    updateUserThemePreference,
  } = useUser();
  const { theme, setTheme } = useTheme();
  const { popup, setPopup } = usePopup();

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

  return (
    <>
      {popup}
      <div className="flex flex-col gap-4">
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
                <InputSelect.Item value={ThemePreference.SYSTEM} icon={SvgCpu}>
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

          <InputLayouts.Horizontal
            label="Auto-scroll"
            description="Automatically scroll to new content"
          >
            <Switch
              checked={user?.preferences.auto_scroll}
              onCheckedChange={(checked) => {
                updateUserAutoScroll(checked);
              }}
            />
          </InputLayouts.Horizontal>

          <InputLayouts.Horizontal
            label="Prompt Shortcuts"
            description="Enable keyboard shortcuts for prompts"
          >
            <Switch
              checked={user?.preferences?.shortcut_enabled}
              onCheckedChange={(checked) => {
                updateUserShortcuts(checked);
              }}
            />
          </InputLayouts.Horizontal>
        </Card>
      </div>
    </>
  );
}

function ChatPreferencesSettings() {
  const {
    user,
    updateUserTemperatureOverrideEnabled,
    updateUserPersonalization,
    refreshUser,
  } = useUser();
  const { popup, setPopup } = usePopup();
  const { llmProviders } = useLLMProviders();
  const router = useRouter();
  const pathname = usePathname();
  const [isModelUpdating, setIsModelUpdating] = useState(false);
  const [currentDefaultModel, setCurrentDefaultModel] = useState<string | null>(
    null
  );
  const [isDeleteAllLoading, setIsDeleteAllLoading] = useState(false);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);

  const defaultModel = user?.preferences?.default_model;
  const displayModel = currentDefaultModel ?? defaultModel;

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

  const handleChangeDefaultModel = useCallback(
    async (defaultModel: string | null) => {
      setCurrentDefaultModel(defaultModel);
      setIsModelUpdating(true);

      try {
        const response = await setUserDefaultModel(defaultModel);

        if (response.ok) {
          setPopup({
            message: "Default model updated successfully",
            type: "success",
          });
          refreshUser();
          router.refresh();
        } else {
          setCurrentDefaultModel(user?.preferences?.default_model ?? null);
          throw new Error("Failed to update default model");
        }
      } catch (error) {
        setCurrentDefaultModel(user?.preferences?.default_model ?? null);
        setPopup({
          message: "Failed to update default model",
          type: "error",
        });
      } finally {
        setIsModelUpdating(false);
      }
    },
    [user, refreshUser, router, setPopup]
  );

  const handleDeleteAllChats = useCallback(async () => {
    setIsDeleteAllLoading(true);
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
      setIsDeleteAllLoading(false);
      setShowDeleteConfirmation(false);
    }
  }, [pathname, router, setPopup]);

  return (
    <>
      {popup}
      <div className="flex flex-col gap-4">
        <Card>
          <div>
            <div className="flex items-center gap-2 mb-2">
              <h3 className="text-lg font-medium">Default Model</h3>
              {isModelUpdating && <SimpleLoader />}
            </div>
            <LLMSelector
              userSettings
              llmProviders={llmProviders ?? []}
              currentLlm={
                displayModel
                  ? structureValue(
                      parseLlmDescriptor(displayModel).name,
                      parseLlmDescriptor(displayModel).provider,
                      parseLlmDescriptor(displayModel).modelName
                    )
                  : null
              }
              requiresImageGeneration={false}
              onSelect={(selected) => {
                if (selected === null) {
                  void handleChangeDefaultModel(null);
                } else {
                  const { modelName, provider, name } =
                    parseLlmDescriptor(selected);
                  if (modelName && name) {
                    void handleChangeDefaultModel(
                      structureValue(name, provider, modelName)
                    );
                  }
                }
              }}
            />
          </div>

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

        <Card>
          <InputLayouts.Horizontal
            label="Use memories"
            description="Allow Onyx to reference stored memories in future chats."
          >
            <Switch
              checked={personalizationValues.use_memories}
              onCheckedChange={(checked) => toggleUseMemories(checked)}
            />
          </InputLayouts.Horizontal>

          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-medium">Memories</h3>
                <SubLabel>
                  Keep personal notes that should inform future chats.
                </SubLabel>
              </div>
              <Button tertiary onClick={addMemory}>
                Add Memory
              </Button>
            </div>
            {personalizationValues.memories.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No memories saved yet.
              </p>
            ) : (
              <div className="max-h-64 overflow-y-auto flex flex-col gap-3 pr-1">
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
              </div>
            )}
          </div>

          <div className="flex justify-end">
            <Button
              onClick={() => {
                void handleSavePersonalization();
              }}
              disabled={isSavingPersonalization}
            >
              {isSavingPersonalization
                ? "Saving Personalization..."
                : "Save Personalization"}
            </Button>
          </div>
        </Card>

        <Card>
          <div className="space-y-3">
            <div>
              <h3 className="text-lg font-medium">Delete All Chats</h3>
              <p className="text-sm text-neutral-600 dark:text-neutral-400">
                This will permanently delete all your chat sessions and cannot
                be undone.
              </p>
            </div>
            {!showDeleteConfirmation ? (
              <Button
                danger
                onClick={() => setShowDeleteConfirmation(true)}
                leftIcon={SvgTrash}
              >
                Delete All Chats
              </Button>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-neutral-600 dark:text-neutral-400">
                  Are you sure you want to delete all your chat sessions?
                </p>
                <div className="flex gap-2">
                  <Button
                    danger
                    onClick={() => {
                      void handleDeleteAllChats();
                    }}
                    disabled={isDeleteAllLoading}
                  >
                    {isDeleteAllLoading ? "Deleting..." : "Yes, Delete All"}
                  </Button>
                  <Button
                    secondary
                    onClick={() => setShowDeleteConfirmation(false)}
                    disabled={isDeleteAllLoading}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>
    </>
  );
}

function AccountsAccessSettings() {
  const { user } = useUser();
  const { popup, setPopup } = usePopup();
  const authType = useAuthType();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = authType && authType !== AuthType.DISABLED;

  const handleChangePassword = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (newPassword !== confirmPassword) {
        setPopup({ message: "New passwords do not match", type: "error" });
        return;
      }

      setIsLoading(true);

      try {
        const response = await fetch("/api/password/change-password", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            old_password: currentPassword,
            new_password: newPassword,
          }),
        });

        if (response.ok) {
          setPopup({
            message: "Password changed successfully",
            type: "success",
          });
          setCurrentPassword("");
          setNewPassword("");
          setConfirmPassword("");
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
      } finally {
        setIsLoading(false);
      }
    },
    [currentPassword, newPassword, confirmPassword, setPopup]
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
      <div className="flex flex-col gap-4">
        {showPasswordSection && (
          <Card>
            <div className="space-y-2">
              <h3 className="text-lg font-medium">Change Password</h3>
              <SubLabel>
                Enter your current password and new password to change your
                password.
              </SubLabel>
            </div>
            <form onSubmit={handleChangePassword} className="space-y-4">
              <div>
                <label
                  htmlFor="currentPassword"
                  className="text-sm font-medium"
                >
                  Current Password
                </label>
                <InputTypeIn
                  id="currentPassword"
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                  className="mt-2"
                />
              </div>
              <div>
                <label htmlFor="newPassword" className="text-sm font-medium">
                  New Password
                </label>
                <InputTypeIn
                  id="newPassword"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  className="mt-2"
                />
              </div>
              <div>
                <label
                  htmlFor="confirmPassword"
                  className="text-sm font-medium"
                >
                  Confirm New Password
                </label>
                <InputTypeIn
                  id="confirmPassword"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  className="mt-2"
                />
              </div>
              <div className="flex justify-end">
                <Button type="submit" disabled={isLoading}>
                  {isLoading ? "Changing..." : "Change Password"}
                </Button>
              </div>
            </form>
          </Card>
        )}

        {showTokensSection && (
          <Card>
            <h2 className="text-xl font-bold mb-4">Personal Access Tokens</h2>
            <p className="text-sm text-text-03 mb-4">
              Create tokens to authenticate API requests. Tokens inherit all
              your permissions.
            </p>
            <PATManagement />
          </Card>
        )}
      </div>
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
      <div className="flex flex-col gap-4">
        <Card>
          <div>
            <h3 className="text-lg font-medium mb-4">Connected Services</h3>
            <p className="text-sm text-muted-foreground mb-4">
              Manage your connected services to search across all your content.
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
      </div>
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
          <div className="flex flex-col px-2 py-6 w-[12.5rem]">
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
          <div className="px-4 py-6">
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
