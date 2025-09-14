"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
import { useContext, useEffect, useRef, useState } from "react";
import { Modal } from "@/components/Modal";
import { getDisplayNameForModel, LlmDescriptor } from "@/lib/hooks";
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
import { FiTrash2 } from "react-icons/fi";
import { deleteAllChatSessions } from "../lib";
import { useChatContext } from "@/components/context/ChatContext";

type SettingsSection = "settings" | "password";

export function UserSettingsModal({
  setPopup,
  llmProviders,
  onClose,
  setCurrentLlm,
  defaultModel,
}: {
  setPopup: (popupSpec: PopupSpec | null) => void;
  llmProviders: LLMProviderDescriptor[];
  setCurrentLlm?: (newLlm: LlmDescriptor) => void;
  onClose: () => void;
  defaultModel: string | null;
}) {
  const { t } = useTranslation();
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

  const handleChangedefaultModel = async (defaultModel: string | null) => {
    try {
      const response = await setUserDefaultModel(defaultModel);

      if (response.ok) {
        if (defaultModel && setCurrentLlm) {
          setCurrentLlm(destructureValue(defaultModel));
        }
        setPopup({
          message: t(k.DEFAULT_MODEL_UPDATED_SUCCESS),
          type: "success",
        });
        refreshUser();
        router.refresh();
      } else {
        throw new Error(t(k.FAILED_TO_UPDATE_DEFAULT_MODEL));
      }
    } catch (error) {
      setPopup({
        message: t(k.FAILED_TO_UPDATE_DEFAULT_MODEL),
        type: "error",
      });
    }
  };

  const settings = useContext(SettingsContext);
  const autoScroll = settings?.settings?.auto_scroll;

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setPopup({ message: t(k.PASSWORDS_DO_NOT_MATCH), type: "error" });
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
          message: t(k.PASSWORD_CHANGED_SUCCESS),
          type: "success",
        });
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
      } else {
        const errorData = await response.json();
        setPopup({
          message: errorData.detail || t(k.FAILED_TO_CHANGE_PASSWORD),
          type: "error",
        });
      }
    } catch (error) {
      setPopup({
        message: t(k.ERROR_CHANGING_PASSWORD),
        type: "error",
      });
    } finally {
      setIsLoading(false);
    }
  };
  const showPasswordSection = user?.password_configured;

  const handleDeleteAllChats = async () => {
    setIsDeleteAllLoading(true);
    try {
      const response = await deleteAllChatSessions();
      if (response.ok) {
        setPopup({
          message: t(k.ALL_CHAT_SESSIONS_DELETED),
          type: "success",
        });
        refreshChatSessions();
        router.push("/chat");
      } else {
        throw new Error(t(k.FAILED_TO_DELETE_ALL_SESSIONS));
      }
    } catch (error) {
      setPopup({
        message: t(k.FAILED_TO_DELETE_ALL_SESSIONS),
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
        showPasswordSection ? "max-w-3xl" : "max-w-xl"
      }`}
    >
      <div className="p-2">
        <h2 className="text-xl font-bold mb-4">{t(k.USER_SETTINGS)}</h2>
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
                      {t(k.SETTINGS)}
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
                      {t(k.PASSWORD1)}
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
                  <h3 className="text-lg font-medium">{t(k.THEME)}</h3>
                  <Select
                    value={selectedTheme}
                    onValueChange={(value) => {
                      setSelectedTheme(value);
                      setTheme(value);
                    }}
                  >
                    <SelectTrigger className="w-full mt-2">
                      <SelectValue
                        placeholder={t(k.SELECT_THEME_PLACEHOLDER)}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem
                        value="system"
                        icon={<Monitor className="h-4 w-4" />}
                      >
                        {t(k.SYSTEM)}
                      </SelectItem>
                      <SelectItem
                        value="light"
                        icon={<Sun className="h-4 w-4" />}
                      >
                        {t(k.LIGHT)}
                      </SelectItem>
                      <SelectItem icon={<Moon />} value="dark">
                        {t(k.DARK)}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-lg font-medium">{t(k.AUTO_SCROLL)}</h3>
                    <SubLabel>{t(k.AUTOMATICALLY_SCROLL_TO_NEW_CO)}</SubLabel>
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
                      {t(k.TEMPERATURE_OVERRIDE)}
                    </h3>
                    <SubLabel>{t(k.SET_THE_TEMPERATURE_FOR_THE_LL)}</SubLabel>
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
                    <h3 className="text-lg font-medium">
                      {t(k.PROMPT_SHORTCUTS)}
                    </h3>
                    <SubLabel>{t(k.ENABLE_KEYBOARD_SHORTCUTS_FOR)}</SubLabel>
                  </div>
                  <Switch
                    checked={user?.preferences?.shortcut_enabled}
                    onCheckedChange={(checked) => {
                      updateUserShortcuts(checked);
                    }}
                  />
                </div>
                <div>
                  <h3 className="text-lg font-medium">{t(k.DEFAULT_MODEL)}</h3>
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
                <div className="pt-4 border-t border-border">
                  {!showDeleteConfirmation ? (
                    <div className="space-y-3">
                      <p className="text-sm text-neutral-600 ">
                        {t(k.THIS_WILL_PERMANENTLY_DELETE_A)}
                      </p>
                      <Button
                        variant="destructive"
                        className="w-full flex items-center justify-center"
                        onClick={() => setShowDeleteConfirmation(true)}
                      >
                        <FiTrash2 className="mr-2" size={14} />
                        {t(k.DELETE_ALL_CHATS)}
                      </Button>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <p className="text-sm text-neutral-600 ">
                        {t(k.ARE_YOU_SURE_YOU_WANT_TO_DELET4)}
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
                            ? t(k.DELETING1)
                            : t(k.YES_DELETE_ALL)}
                        </Button>
                        <Button
                          variant="outline"
                          className="flex-1"
                          onClick={() => setShowDeleteConfirmation(false)}
                          disabled={isDeleteAllLoading}
                        >
                          {t(k.CANCEL)}
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
                  <h3 className="text-xl font-medium">
                    {t(k.CHANGE_PASSWORD)}
                  </h3>
                  <SubLabel>{t(k.ENTER_YOUR_CURRENT_PASSWORD_AN)}</SubLabel>
                </div>
                <form onSubmit={handleChangePassword} className="w-full">
                  <div className="w-full">
                    <label htmlFor="currentPassword" className="block mb-1">
                      {t(k.CURRENT_PASSWORD)}
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
                      {t(k.NEW_PASSWORD2)}
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
                      {t(k.CONFIRM_NEW_PASSWORD)}
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
                    {isLoading ? t(k.CHANGING) : t(k.CHANGE_PASSWORD)}
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
