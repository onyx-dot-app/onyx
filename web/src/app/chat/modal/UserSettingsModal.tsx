import { useContext, useEffect, useRef, useState } from "react";
import { Modal } from "@/components/Modal";
import { getDisplayNameForModel, LlmOverride } from "@/lib/hooks";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";

import { destructureValue, structureValue } from "@/lib/llm/utils";
import { setUserDefaultModel } from "@/lib/users/UserSettings";
import { useRouter } from "next/navigation";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { useUser } from "@/components/user/UserProvider";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { SubLabel } from "@/components/admin/connectors/Field";
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

type SettingsSection = "settings" | "password";

export function UserSettingsModal({
  setPopup,
  llmProviders,
  onClose,
  setLlmOverride,
  defaultModel,
}: {
  setPopup: (popupSpec: PopupSpec | null) => void;
  llmProviders: LLMProviderDescriptor[];
  setLlmOverride?: (newOverride: LlmOverride) => void;
  onClose: () => void;
  defaultModel: string | null;
}) {
  const { refreshUser, user, updateUserAutoScroll, updateUserShortcuts } =
    useUser();
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
    ? destructureValue(defaultModel)
    : null;
  const modelOptionsByProvider = new Map<
    string,
    { name: string; value: string }[]
  >();
  llmProviders.forEach((llmProvider) => {
    const providerOptions = llmProvider.model_names.map(
      (modelName: string) => ({
        name: getDisplayNameForModel(modelName),
        value: modelName,
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

    (llmProvider.display_model_names || llmProvider.model_names).forEach(
      (modelName) => {
        if (!uniqueModelNames.has(modelName)) {
          uniqueModelNames.add(modelName);
          llmOptionsByProvider[llmProvider.provider].push({
            name: modelName,
            value: structureValue(
              llmProvider.name,
              llmProvider.provider,
              modelName
            ),
          });
        }
      }
    );
  });

  const llmOptions = Object.entries(llmOptionsByProvider).flatMap(
    ([provider, options]) => [...options]
  );

  const router = useRouter();
  const handleChangedefaultModel = async (defaultModel: string | null) => {
    try {
      const response = await setUserDefaultModel(defaultModel);

      if (response.ok) {
        if (defaultModel && setLlmOverride) {
          setLlmOverride(destructureValue(defaultModel));
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

  const settings = useContext(SettingsContext);
  const autoScroll = settings?.settings?.auto_scroll;

  const checked =
    user?.preferences?.auto_scroll === null
      ? autoScroll
      : user?.preferences?.auto_scroll;

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
  const showPasswordSection = user?.password_configured;

  return (
    <Modal
      onOutsideClick={onClose}
      width={`rounded-lg w-full ${
        showPasswordSection ? "max-w-3xl" : "max-w-xl"
      }`}
    >
      <div className="p-2">
        <h2 className="text-xl font-bold mb-4">User Settings</h2>
        <Separator className="mb-6" />
        <div className="flex">
          {showPasswordSection && (
            <div className="w-1/4 pr-4">
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
                </ul>
              </nav>
            </div>
          )}
          <div className={`${showPasswordSection ? "w-3/4 pl-4" : "w-full"}`}>
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
                    checked={checked}
                    onCheckedChange={(checked) => {
                      updateUserAutoScroll(checked);
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
                            destructureValue(defaultModel).provider,
                            "",
                            destructureValue(defaultModel).modelName
                          )
                        : null
                    }
                    requiresImageGeneration={false}
                    onSelect={(selected) => {
                      if (selected === null) {
                        handleChangedefaultModel(null);
                      } else {
                        const { modelName, provider, name } =
                          destructureValue(selected);
                        if (modelName && name) {
                          handleChangedefaultModel(
                            structureValue(provider, "", modelName)
                          );
                        }
                      }
                    }}
                  />
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
          </div>
        </div>
      </div>
    </Modal>
  );
}
