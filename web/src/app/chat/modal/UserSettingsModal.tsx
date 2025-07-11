import { useContext, useEffect, useRef, useState } from "react";
import { Modal } from "@/components/Modal";
import { getDisplayNameForModel, LlmDescriptor } from "@/lib/hooks";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";

import { parseLlmDescriptor, structureValue } from "@/lib/llm/utils";
import { setUserDefaultModel } from "@/lib/users/UserSettings";
import { usePathname, useRouter } from "next/navigation";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { useUser } from "@/components/user/UserProvider";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { SubLabel } from "@/components/Field";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { LLMSelector } from "@/components/llm/LLMSelector";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FiTrash2, FiExternalLink } from "react-icons/fi";
import { deleteAllChatSessions } from "../lib";
import { useChatContext } from "@/components/context/ChatContext";
import { FederatedConnectorOAuthStatus } from "@/components/chat/FederatedOAuthModal";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources, CCPairBasicInfo } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";

type SettingsSection = "settings" | "password" | "connectors";

export function UserSettingsModal({
  setPopup,
  llmProviders,
  onClose,
  setCurrentLlm,
  defaultModel,
  ccPairs,
  federatedConnectors,
  refetchFederatedConnectors,
}: {
  setPopup: (popupSpec: PopupSpec | null) => void;
  llmProviders: LLMProviderDescriptor[];
  setCurrentLlm?: (newLlm: LlmDescriptor) => void;
  onClose: () => void;
  defaultModel: string | null;
  ccPairs?: CCPairBasicInfo[];
  federatedConnectors?: FederatedConnectorOAuthStatus[];
  refetchFederatedConnectors?: () => void;
}) {
  const {
    refreshUser,
    user,
    updateUserAutoScroll,
    updateUserShortcuts,
    updateUserTemperatureOverrideEnabled,
  } = useUser();
  const { refreshChatSessions } = useChatContext();
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement>(null);
  const messageRef = useRef<HTMLDivElement>(null);
  const { theme, setTheme } = useTheme();
  const [selectedTheme, setSelectedTheme] = useState(theme);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [activeSection, setActiveSection] =
    useState<SettingsSection>("settings");
  const [isDeleteAllLoading, setIsDeleteAllLoading] = useState(false);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState<number | null>(null);

  const hasConnectors =
    (ccPairs && ccPairs.length > 0) ||
    (federatedConnectors && federatedConnectors.length > 0);

  useEffect(() => {
    const container = containerRef.current;
    const message = messageRef.current;

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleEscape);

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
        window.removeEventListener("keydown", handleEscape);
      };
    }

    return () => window.removeEventListener("keydown", handleEscape);
  }, [onClose]);

  const defaultModelDestructured = defaultModel
    ? parseLlmDescriptor(defaultModel)
    : null;
  const modelOptionsByProvider = new Map<
    string,
    { name: string; value: string }[]
  >();
  llmProviders.forEach((llmProvider) => {
    const providerOptions = llmProvider.model_configurations.map(
      (model_configuration) => ({
        name: getDisplayNameForModel(model_configuration.name),
        value: model_configuration.name,
      })
    );
    modelOptionsByProvider.set(llmProvider.name, providerOptions);
  });

  const llmOptionsByProvider: {
    [provider: string]: { name: string; value: string }[];
  } = {};
  const uniqueModelNames = new Set<string>();

  llmProviders.forEach((llmProvider) => {
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
    try {
      const response = await setUserDefaultModel(defaultModel);

      if (response.ok) {
        if (defaultModel && setCurrentLlm) {
          setCurrentLlm(parseLlmDescriptor(defaultModel));
        }
        setPopup({
          message: "Default model updated successfully",
          type: "success",
        });
        refreshUser();
        router.refresh();
      } else {
        throw new Error("Failed to update default model");
      }
    } catch (error) {
      setPopup({
        message: "Failed to update default model",
        type: "error",
      });
    }
  };

  const handleConnectOAuth = (authorizeUrl: string) => {
    // Redirect to OAuth URL in the same window
    router.push(authorizeUrl);
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

  const settings = useContext(SettingsContext);
  const autoScroll = settings?.settings?.auto_scroll;

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

  const showPasswordSection = user?.password_configured;

  const handleDeleteAllChats = async () => {
    setIsDeleteAllLoading(true);
    try {
      const response = await deleteAllChatSessions();
      if (response.ok) {
        setPopup({
          message: "All your chat sessions have been deleted.",
          type: "success",
        });
        refreshChatSessions();
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
    <Modal
      onOutsideClick={onClose}
      width={`rounded-lg w-full ${
        showPasswordSection || hasConnectors ? "max-w-3xl" : "max-w-xl"
      }`}
    >
      <div className="p-2 max-h-[80vh] flex flex-col">
        <h2 className="text-xl font-bold mb-4">User Settings</h2>
        <Separator className="mb-6" />
        <div className="flex flex-1 min-h-0">
          {(showPasswordSection || hasConnectors) && (
            <div className="w-1/4 pr-4 flex-shrink-0">
              <nav>
                <ul className="space-y-2">
                  <li>
                    <button
                      className={`w-full text-base text-left py-2 px-4 rounded hover:bg-neutral-100 dark:hover:bg-neutral-700 ${
                        activeSection === "settings"
                          ? "bg-neutral-100 dark:bg-neutral-700 font-semibold"
                          : ""
                      }`}
                      onClick={() => setActiveSection("settings")}
                    >
                      Settings
                    </button>
                  </li>
                  {showPasswordSection && (
                    <li>
                      <button
                        className={`w-full text-left py-2 px-4 rounded hover:bg-neutral-100 dark:hover:bg-neutral-700 ${
                          activeSection === "password"
                            ? "bg-neutral-100 dark:bg-neutral-700 font-semibold"
                            : ""
                        }`}
                        onClick={() => setActiveSection("password")}
                      >
                        Password
                      </button>
                    </li>
                  )}
                  {hasConnectors && (
                    <li>
                      <button
                        className={`w-full text-base text-left py-2 px-4 rounded hover:bg-neutral-100 dark:hover:bg-neutral-700 ${
                          activeSection === "connectors"
                            ? "bg-neutral-100 dark:bg-neutral-700 font-semibold"
                            : ""
                        }`}
                        onClick={() => setActiveSection("connectors")}
                      >
                        Connectors
                      </button>
                    </li>
                  )}
                </ul>
              </nav>
            </div>
          )}
          <div
            className={`${
              showPasswordSection || hasConnectors
                ? "w-3/4 pl-4 pr-3"
                : "w-full pr-3"
            } overflow-y-scroll default-scrollbar`}
          >
            {activeSection === "settings" && (
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-medium">Theme</h3>
                  <Select
                    value={selectedTheme}
                    onValueChange={(value) => {
                      setSelectedTheme(value);
                      setTheme(value);
                    }}
                  >
                    <SelectTrigger className="w-full mt-2">
                      <SelectValue placeholder="Select theme" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem
                        value="system"
                        icon={<Monitor className="h-4 w-4" />}
                      >
                        System
                      </SelectItem>
                      <SelectItem
                        value="light"
                        icon={<Sun className="h-4 w-4" />}
                      >
                        Light
                      </SelectItem>
                      <SelectItem icon={<Moon />} value="dark">
                        Dark
                      </SelectItem>
                    </SelectContent>
                  </Select>
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
                  <h3 className="text-lg font-medium">Default Model</h3>
                  <LLMSelector
                    userSettings
                    llmProviders={llmProviders}
                    currentLlm={
                      defaultModel
                        ? structureValue(
                            parseLlmDescriptor(defaultModel).provider,
                            "",
                            parseLlmDescriptor(defaultModel).modelName
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
                            structureValue(provider, "", modelName)
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
                        This will permanently delete all your chat sessions and
                        cannot be undone.
                      </p>
                      <Button
                        variant="destructive"
                        className="w-full flex items-center justify-center"
                        onClick={() => setShowDeleteConfirmation(true)}
                      >
                        <FiTrash2 className="mr-2" size={14} />
                        Delete All Chats
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <p className="text-sm text-neutral-600 dark:text-neutral-400">
                        Are you sure you want to delete all your chat sessions?
                      </p>
                      <div className="flex gap-2">
                        <Button
                          type="button"
                          variant="destructive"
                          className="flex-1 flex items-center justify-center"
                          onClick={handleDeleteAllChats}
                          disabled={isDeleteAllLoading}
                        >
                          {isDeleteAllLoading
                            ? "Deleting..."
                            : "Yes, Delete All"}
                        </Button>
                        <Button
                          variant="outline"
                          className="flex-1"
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
            {activeSection === "password" && (
              <div className="space-y-6">
                <div className="space-y-2">
                  <h3 className="text-xl font-medium">Change Password</h3>
                  <SubLabel>
                    Enter your current password and new password to change your
                    password.
                  </SubLabel>
                </div>
                <form onSubmit={handleChangePassword} className="w-full">
                  <div className="w-full">
                    <label htmlFor="currentPassword" className="block mb-1">
                      Current Password
                    </label>
                    <Input
                      id="currentPassword"
                      type="password"
                      value={currentPassword}
                      onChange={(e) => setCurrentPassword(e.target.value)}
                      required
                      className="w-full"
                    />
                  </div>
                  <div className="w-full">
                    <label htmlFor="newPassword" className="block mb-1">
                      New Password
                    </label>
                    <Input
                      id="newPassword"
                      type="password"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      required
                      className="w-full"
                    />
                  </div>
                  <div className="w-full">
                    <label htmlFor="confirmPassword" className="block mb-1">
                      Confirm New Password
                    </label>
                    <Input
                      id="confirmPassword"
                      type="password"
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      required
                      className="w-full"
                    />
                  </div>
                  <Button type="submit" disabled={isLoading} className="w-full">
                    {isLoading ? "Changing..." : "Change Password"}
                  </Button>
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

                        return Object.values(groupedConnectors).map((group) => (
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
                                    variant="outline"
                                    size="sm"
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
                                    size="sm"
                                    onClick={() => {
                                      if (connector.authorize_url) {
                                        handleConnectOAuth(
                                          connector.authorize_url
                                        );
                                      }
                                    }}
                                    disabled={!connector.authorize_url}
                                  >
                                    <FiExternalLink
                                      className="mr-2"
                                      size={14}
                                    />
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
          </div>
        </div>
      </div>
    </Modal>
  );
}
