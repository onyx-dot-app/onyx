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
import { Label } from "@/components/admin/connectors/Field";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { useChatContext } from "@/components/context/ChatContext";
import { InputPromptsSection } from "./InputPromptsSection";
import { LLMSelector } from "@/components/llm/LLMSelector";
import { ModeToggle } from "./ThemeToggle";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

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
  const {
    refreshUser,
    user,
    updateUserAutoScroll,
    updateUserShortcuts,
    updateUserTemperatureOverrideEnabled,
  } = useUser();
  const containerRef = useRef<HTMLDivElement>(null);
  const messageRef = useRef<HTMLDivElement>(null);
  const { theme, setTheme } = useTheme();
  const [selectedTheme, setSelectedTheme] = useState(theme);

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
  const defaultProvider = llmProviders.find(
    (llmProvider) => llmProvider.is_default_provider
  );
  const settings = useContext(SettingsContext);
  const autoScroll = settings?.enterpriseSettings?.auto_scroll;

  const checked =
    user?.preferences?.auto_scroll === null
      ? autoScroll
      : user?.preferences?.auto_scroll;

  return (
    <Modal onOutsideClick={onClose} width="rounded-lg w-full max-w-xl">
      <div className="p-2">
        <div>
          <h2 className="text-2xl font-bold">User settings</h2>
        </div>

        <div className="space-y-6 py-4">
          {/* Auto-scroll Section */}
          <div className="flex items-center justify-between">
            <div className="space-y-1">
              <h4 className="text-base font-medium">Auto-scroll</h4>
              <p className="text-sm text-neutral-500 dark:text-neutral-400">
                Automatically scroll to new content
              </p>
            </div>
            <Switch
              size="sm"
              checked={checked}
              onCheckedChange={(checked) => {
                updateUserAutoScroll(checked);
              }}
            />
          </div>

          {/* Prompt Shortcuts Section */}
          <div className="flex items-center justify-between">
            <div className="space-y-1">
              <h4 className="text-base font-medium">Prompt Shortcuts</h4>
              <p className="text-sm text-neutral-500 dark:text-neutral-400">
                Enable keyboard shortcuts for prompts
              </p>
            </div>
            <Switch
              size="sm"
              checked={user?.preferences?.shortcut_enabled}
              onCheckedChange={(checked) => {
                updateUserShortcuts(checked);
              }}
            />
          </div>

          {/* Temperature Override Section */}
          <div className="flex items-center justify-between">
            <div className="space-y-1">
              <h4 className="text-base font-medium">Temperature Override</h4>
              <p className="text-sm text-neutral-500 dark:text-neutral-400">
                Override default temperature settings
              </p>
            </div>
            <Switch
              size="sm"
              checked={user?.preferences?.temperature_override_enabled}
              onCheckedChange={(checked) => {
                updateUserTemperatureOverrideEnabled(checked);
              }}
            />
          </div>

          <Separator className="my-4" />

          {/* Theme Section */}
          <div className="space-y-3">
            <h4 className="text-base font-medium">Theme</h4>
            <Select
              value={selectedTheme}
              onValueChange={(value) => {
                setSelectedTheme(value);
                setTheme(value);
              }}
            >
              <SelectTrigger className="w-full">
                <div className="flex items-center gap-2">
                  {theme === "system" ? (
                    <Monitor className="h-4 w-4" />
                  ) : theme === "light" ? (
                    <Sun className="h-4 w-4" />
                  ) : (
                    <Moon className="h-4 w-4" />
                  )}
                  <SelectValue placeholder="Select theme" />
                </div>
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  icon={<Monitor className="h-4 w-4" />}
                  value="system"
                >
                  System
                </SelectItem>
                <SelectItem icon={<Sun className="h-4 w-4" />} value="light">
                  Light
                </SelectItem>
                <SelectItem icon={<Moon className="h-4 w-4" />} value="dark">
                  Dark
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Separator className="my-4" />

          {/* Default Model Section */}
          <div className="space-y-3">
            <h4 className="text-base font-medium">Default Model</h4>
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
      </div>
    </Modal>
  );
}
