import {
  Dispatch,
  SetStateAction,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { Modal } from "@/components/Modal";
import Text from "@/components/ui/text";
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

export function UserSettingsModal({
  setPopup,
  llmProviders,
  onClose,
  setLlmOverride,
  defaultModel,
}: {
  setPopup: (popupSpec: PopupSpec | null) => void;
  llmProviders: LLMProviderDescriptor[];
  setLlmOverride?: Dispatch<SetStateAction<LlmOverride>>;
  onClose: () => void;
  defaultModel: string | null;
}) {
  const { inputPrompts, refreshInputPrompts } = useChatContext();
  const { refreshUser, user, updateUserAutoScroll, updateUserShortcuts } =
    useUser();
  const containerRef = useRef<HTMLDivElement>(null);
  const messageRef = useRef<HTMLDivElement>(null);

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
    <Modal onOutsideClick={onClose} width="rounded-lg w-full bg-white max-w-xl">
      <>
        <div className="flex mb-4">
          <h2 className="text-2xl text-emphasis font-bold flex my-auto">
            User settings
          </h2>
        </div>

        <div className="flex flex-col gap-y-2">
          <div className="flex items-center gap-x-2">
            <Switch
              size="sm"
              checked={checked}
              onCheckedChange={(checked) => {
                updateUserAutoScroll(checked);
              }}
            />
            <Label className="text-sm">Enable auto-scroll</Label>
          </div>
          <div className="flex items-center gap-x-2">
            <Switch
              size="sm"
              checked={user?.preferences?.shortcut_enabled}
              onCheckedChange={(checked) => {
                updateUserShortcuts(checked);
                refreshUser();
              }}
            />
            <Label className="text-sm">Enable Prompt Shortcuts</Label>
          </div>
        </div>

        <Separator />

        <h3 className="text-lg text-emphasis font-bold mb-2 ">Default Model</h3>
        <div
          className="w-full max-h-96 overflow-y-auto flex text-sm flex-col border rounded-md"
          ref={containerRef}
        >
          <div
            ref={messageRef}
            className="sticky top-0 bg-background-100 p-2 text-xs text-emphasis font-medium"
            style={{ display: "none" }}
          >
            Scroll to see all options
          </div>
          <LLMSelector
            llmProviders={llmProviders}
            currentLlm={
              defaultModelDestructured
                ? structureValue(
                    defaultModelDestructured.provider,
                    "",
                    defaultModelDestructured.modelName
                  )
                : null
            }
            userDefault={null}
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
      </>
    </Modal>
  );
}
