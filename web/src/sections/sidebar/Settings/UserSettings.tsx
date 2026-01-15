"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useAuthType } from "@/lib/hooks";
import { parseLlmDescriptor, structureValue } from "@/lib/llm/utils";
import { setUserDefaultModel } from "@/lib/userSettings";
import { usePathname, useRouter } from "next/navigation";
import type { Route } from "next";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useUser } from "@/components/user/UserProvider";
import { ThemePreference } from "@/lib/types";
import { AuthType } from "@/lib/constants";
import Switch from "@/refresh-components/inputs/Switch";
import { SubLabel } from "@/components/Field";
import LLMSelector from "@/components/llm/LLMSelector";
import { useTheme } from "next-themes";
import Button from "@/refresh-components/buttons/Button";
import { deleteAllChatSessions } from "@/app/chat/services/lib";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import useFederatedOAuthStatus from "@/hooks/useFederatedOAuthStatus";
import useCCPairs from "@/hooks/useCCPairs";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import Text from "@/refresh-components/texts/Text";
import PATManagement from "@/components/user/PATManagement";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import {
  SvgCpu,
  SvgExternalLink,
  SvgMoon,
  SvgSettings,
  SvgSun,
  SvgTrash,
  SvgXOctagon,
} from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import { useModal } from "@/refresh-components/contexts/ModalContext";

type SettingsSection =
  | "general"
  | "password"
  | "connectors"
  | "personalization"
  | "tokens";

export default function UserSettings() {
  const {
    refreshUser,
    user,
    updateUserAutoScroll,
    updateUserShortcuts,
    updateUserTemperatureOverrideEnabled,
    updateUserPersonalization,
    updateUserThemePreference,
  } = useUser();
  const { llmProviders } = useLLMProviders();
  const authType = useAuthType();
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement>(null);
  const messageRef = useRef<HTMLDivElement>(null);
  const { theme, setTheme } = useTheme();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isModelUpdating, setIsModelUpdating] = useState(false);
  const [activeSection, setActiveSection] =
    useState<SettingsSection>("general");
  // show updates in the UI instantly without waiting for an API call to finish
  const [currentDefaultModel, setCurrentDefaultModel] = useState<string | null>(
    null
  );
  const [isDeleteAllLoading, setIsDeleteAllLoading] = useState(false);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState<number | null>(null);
  const { popup, setPopup } = usePopup();
  const modal = useModal();

  // Fetch federated-connector info so the modal can list/refresh them
  const {
    connectors: federatedConnectors,
    refetch: refetchFederatedConnectors,
    isLoading: isFederatedLoading,
  } = useFederatedOAuthStatus();

  const { ccPairs, isLoading: isCCPairsLoading } = useCCPairs();

  const defaultModel = user?.preferences?.default_model;

  // Initialize currentDefaultModel from user preferences
  useEffect(() => {
    if (currentDefaultModel === null && defaultModel) {
      setCurrentDefaultModel(defaultModel);
    }
  }, [defaultModel, currentDefaultModel]);

  // Use currentDefaultModel for display, falling back to defaultModel
  const displayModel = currentDefaultModel ?? defaultModel;

  const hasConnectors = ccPairs.length > 0 || federatedConnectors.length > 0;

  const isLoadingConnectors = isCCPairsLoading || isFederatedLoading;

  const showPasswordSection = Boolean(user?.password_configured);

  const {
    personalizationValues,
    updatePersonalizationField,
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

  const sections = useMemo(() => {
    const visibleSections: { id: SettingsSection; label: string }[] = [
      { id: "general", label: "General" },
      { id: "personalization", label: "Personalization" },
    ];

    if (showPasswordSection) {
      visibleSections.push({ id: "password", label: "Password" });
    }

    if (authType && authType !== AuthType.DISABLED) {
      visibleSections.push({ id: "tokens", label: "Access Tokens" });
    }

    visibleSections.push({ id: "connectors", label: "Connectors" });

    return visibleSections;
  }, [showPasswordSection, authType]);

  useEffect(() => {
    if (!sections.some((section) => section.id === activeSection)) {
      setActiveSection(sections[0]?.id ?? "general");
    }
  }, [sections, activeSection]);

  useEffect(() => {
    const container = containerRef.current;
    const message = messageRef.current;

    if (container && message) {
      const checkScrollable = () => {
        if (container.scrollHeight > container.clientHeight) {
          message.style.display = "block";
        } else {
          message.style.display = "none";
        }
      };
      checkScrollable();
      window.addEventListener("resize", checkScrollable);
      return () => {
        window.removeEventListener("resize", checkScrollable);
      };
    }
  }, []);

  const modelOptionsByProvider = new Map<
    string,
    { name: string; value: string }[]
  >();
  llmProviders?.forEach((llmProvider) => {
    const providerOptions = llmProvider.model_configurations.map(
      (model_configuration) => ({
        name: model_configuration.display_name || model_configuration.name,
        value: model_configuration.name,
      })
    );
    modelOptionsByProvider.set(llmProvider.name, providerOptions);
  });

  const llmOptionsByProvider: {
    [provider: string]: { name: string; value: string }[];
  } = {};
  const uniqueModelNames = new Set<string>();

  llmProviders?.forEach((llmProvider) => {
    if (!llmOptionsByProvider[llmProvider.provider]) {
      llmOptionsByProvider[llmProvider.provider] = [];
    }

    llmProvider.model_configurations.forEach((modelConfiguration) => {
      if (!uniqueModelNames.has(modelConfiguration.name)) {
        uniqueModelNames.add(modelConfiguration.name);
        const llmOptions = llmOptionsByProvider[llmProvider.provider];
        if (llmOptions) {
          llmOptions.push({
            name: modelConfiguration.name,
            value: structureValue(
              llmProvider.name,
              llmProvider.provider,
              modelConfiguration.name
            ),
          });
        }
      }
    });
  });

  const handleChangedefaultModel = async (defaultModel: string | null) => {
    // Update UI instantly
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
        // refresh so that the new default model is reflected in the
        // LLMManager / the UI
        router.refresh();
      } else {
        // Revert on failure
        setCurrentDefaultModel(user?.preferences?.default_model ?? null);
        throw new Error("Failed to update default model");
      }
    } catch (error) {
      // Revert on error
      setCurrentDefaultModel(user?.preferences?.default_model ?? null);
      setPopup({
        message: "Failed to update default model",
        type: "error",
      });
    } finally {
      setIsModelUpdating(false);
    }
  };

  const handleConnectOAuth = (authorizeUrl: string) => {
    // Redirect to OAuth URL in the same window
    router.push(authorizeUrl as Route);
  };

  const handleDisconnectOAuth = async (connectorId: number) => {
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
  };

  const handleChangePassword = async (e: React.FormEvent) => {
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
        setPopup({ message: "Password changed successfully", type: "success" });
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
  };

  const pathname = usePathname();

  const handleDeleteAllChats = async () => {
    setIsDeleteAllLoading(true);
    try {
      const response = await deleteAllChatSessions();
      if (response.ok) {
        setPopup({
          message: "All your chat sessions have been deleted.",
          type: "success",
        });
        // refreshChatSessions();
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
  };

  return (
    <>
      {popup}

      <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
        <Modal.Content tall>
          <Modal.Header
            icon={SvgSettings}
            title="Settings"
            onClose={() => modal.toggle(false)}
          />
          <Modal.Body twoTone={false}>
            {sections.length > 1 && (
              <nav>
                <ul className="flex flex-row gap-1">
                  {sections.map(({ id, label }) => (
                    <li key={id}>
                      <Button
                        tertiary
                        transient={activeSection === id}
                        disabled={
                          id === "connectors" &&
                          (isLoadingConnectors || !hasConnectors)
                        }
                        onClick={() => setActiveSection(id)}
                      >
                        {label}
                      </Button>
                    </li>
                  ))}
                </ul>
              </nav>
            )}
            <div className="w-full overflow-y-auto">
              {activeSection === "general" && (
                <div className="space-y-6">
                  <div>
                    <h3 className="text-lg font-medium">Theme</h3>
                    <InputSelect
                      defaultValue={theme}
                      onValueChange={(value) => {
                        setTheme(value);
                        updateUserThemePreference(value as ThemePreference);
                      }}
                    >
                      <InputSelect.Trigger />

                      <InputSelect.Content>
                        <InputSelect.Item
                          key={ThemePreference.SYSTEM}
                          value={ThemePreference.SYSTEM}
                          icon={SvgCpu}
                        >
                          System
                        </InputSelect.Item>
                        <InputSelect.Item
                          key={ThemePreference.LIGHT}
                          value={ThemePreference.LIGHT}
                          icon={SvgSun}
                        >
                          Light
                        </InputSelect.Item>
                        <InputSelect.Item
                          key={ThemePreference.DARK}
                          value={ThemePreference.DARK}
                          icon={SvgMoon}
                        >
                          Dark
                        </InputSelect.Item>
                      </InputSelect.Content>
                    </InputSelect>
                  </div>
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-lg font-medium">Auto-scroll</h3>
                      <SubLabel>Automatically scroll to new content</SubLabel>
                    </div>
                    <Switch
                      checked={user?.preferences.auto_scroll}
                      onCheckedChange={(checked) => {
                        updateUserAutoScroll(checked);
                      }}
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-lg font-medium">
                        Temperature override
                      </h3>
                      <SubLabel>Set the temperature for the LLM</SubLabel>
                    </div>
                    <Switch
                      checked={user?.preferences.temperature_override_enabled}
                      onCheckedChange={(checked) => {
                        updateUserTemperatureOverrideEnabled(checked);
                      }}
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-lg font-medium">Prompt Shortcuts</h3>
                      <SubLabel>Enable keyboard shortcuts for prompts</SubLabel>
                    </div>
                    <Switch
                      checked={user?.preferences?.shortcut_enabled}
                      onCheckedChange={(checked) => {
                        updateUserShortcuts(checked);
                      }}
                    />
                  </div>
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
                          handleChangedefaultModel(null);
                        } else {
                          const { modelName, provider, name } =
                            parseLlmDescriptor(selected);
                          if (modelName && name) {
                            handleChangedefaultModel(
                              structureValue(name, provider, modelName)
                            );
                          }
                        }
                      }}
                    />
                  </div>
                  <div className="pt-4 border-t border-border">
                    {!showDeleteConfirmation ? (
                      <div className="space-y-3">
                        <p className="text-sm text-neutral-600 dark:text-neutral-400">
                          This will permanently delete all your chat sessions
                          and cannot be undone.
                        </p>
                        <Button
                          danger
                          onClick={() => setShowDeleteConfirmation(true)}
                          leftIcon={SvgTrash}
                        >
                          Delete All Chats
                        </Button>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        <p className="text-sm text-neutral-600 dark:text-neutral-400">
                          Are you sure you want to delete all your chat
                          sessions?
                        </p>
                        <div className="flex gap-2">
                          <Button
                            danger
                            onClick={handleDeleteAllChats}
                            disabled={isDeleteAllLoading}
                          >
                            {isDeleteAllLoading
                              ? "Deleting..."
                              : "Yes, Delete All"}
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
                </div>
              )}
              {activeSection === "personalization" && (
                <div className="flex flex-col gap-4">
                  <div>
                    <h3 className="text-lg font-medium">Name</h3>
                    <InputTypeIn
                      value={personalizationValues.name}
                      onChange={(event) =>
                        updatePersonalizationField("name", event.target.value)
                      }
                      placeholder="Set how Onyx should refer to you"
                      className="mt-2"
                    />
                    {personalizationValues.name.length === 0 && (
                      <div className="flex items-center gap-1 mt-1">
                        <SvgXOctagon className="h-3 w-3 stroke-status-error-05" />
                        <Text text03 secondaryBody>
                          Please enter a name to continue.
                        </Text>
                      </div>
                    )}
                  </div>
                  <div>
                    <h3 className="text-lg font-medium">Role</h3>
                    <InputTypeIn
                      value={personalizationValues.role}
                      onChange={(event) =>
                        updatePersonalizationField("role", event.target.value)
                      }
                      placeholder="Share your role to tailor responses"
                      className="mt-2"
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-lg font-medium">Use memories</h3>
                      <SubLabel>
                        Allow Onyx to reference stored memories in future chats.
                      </SubLabel>
                    </div>
                    <Switch
                      checked={personalizationValues.use_memories}
                      onCheckedChange={(checked) => toggleUseMemories(checked)}
                    />
                  </div>
                  <div className="border-t border-border pt-4 space-y-3">
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
                      disabled={
                        isSavingPersonalization ||
                        personalizationValues.name.length === 0
                      }
                    >
                      {isSavingPersonalization
                        ? "Saving Personalization..."
                        : "Save Personalization"}
                    </Button>
                  </div>
                </div>
              )}
              {activeSection === "password" && (
                <div className="space-y-6">
                  <div className="space-y-2">
                    <h3 className="text-lg font-medium">Change Password</h3>
                    <SubLabel>
                      Enter your current password and new password to change
                      your password.
                    </SubLabel>
                  </div>
                  <form onSubmit={handleChangePassword} className="w-full">
                    <div className="w-full">
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
                    <div className="w-full">
                      <label
                        htmlFor="newPassword"
                        className="text-sm font-medium"
                      >
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
                    <div className="w-full">
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
                    <div className="flex justify-end w-full">
                      <Button disabled={isLoading}>
                        {isLoading ? "Changing..." : "Change Password"}
                      </Button>
                    </div>
                  </form>
                </div>
              )}
              {activeSection === "connectors" && (
                <div className="space-y-6">
                  <div>
                    <h3 className="text-lg font-medium mb-4">
                      Connected Services
                    </h3>
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
                          // Group connectors by source
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

                          // Helper function to format source names
                          const formatSourceName = (source: string) => {
                            return source
                              .split("_")
                              .map(
                                (word) =>
                                  word.charAt(0).toUpperCase() + word.slice(1)
                              )
                              .join(" ");
                          };

                          return Object.values(groupedConnectors).map(
                            (group) => (
                              <div
                                key={group.source}
                                className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30"
                              >
                                <div className="flex items-center gap-3">
                                  <SourceIcon
                                    sourceType={group.source}
                                    iconSize={24}
                                  />
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
                            )
                          );
                        })()}
                      </div>
                    )}

                    {/* Federated Search Section */}
                    {federatedConnectors && federatedConnectors.length > 0 && (
                      <div className="space-y-3">
                        <h4 className="text-md font-medium text-muted-foreground">
                          Federated Connectors
                        </h4>
                        {(() => {
                          // Helper function to format source names
                          const formatSourceName = (source: string) => {
                            return source
                              .split("_")
                              .map(
                                (word) =>
                                  word.charAt(0).toUpperCase() + word.slice(1)
                              )
                              .join(" ");
                          };

                          return federatedConnectors.map((connector) => {
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
                                      {formatSourceName(
                                        sourceMetadata.displayName
                                      )}
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
                                        handleDisconnectOAuth(
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
                                          handleConnectOAuth(
                                            connector.authorize_url
                                          );
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
                          });
                        })()}
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
                </div>
              )}
              {activeSection === "tokens" && (
                <div>
                  <h2 className="text-xl font-bold mb-4">
                    Personal Access Tokens
                  </h2>
                  <p className="text-sm text-text-03 mb-4">
                    Create tokens to authenticate API requests. Tokens inherit
                    all your permissions.
                  </p>
                  <PATManagement />
                </div>
              )}
            </div>
          </Modal.Body>
        </Modal.Content>
      </Modal>
    </>
  );
}
