"use client";
import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";

import { Label, SubLabel } from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import Title from "@/components/ui/title";
import { Button } from "@/components/ui/button";
import { Settings } from "./interfaces";
import { useRouter } from "next/navigation";
import { DefaultDropdown, Option } from "@/components/Dropdown";
import React, { useContext, useState, useEffect } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { Modal } from "@/components/Modal";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { AnonymousUserPath } from "./AnonymousUserPath";
import { useChatContext } from "@/components/context/ChatContext";
import { EditableValue } from "@/components/EditableValue";
import useSWR from "swr";
import { LLMSelector } from "@/components/llm/LLMSelector";
import { useVisionProviders } from "./hooks/useVisionProviders";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function Checkbox({
  label,
  sublabel,
  checked,
  onChange,
}: {
  label: string;
  sublabel?: string;
  checked: boolean;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <label className="flex text-xs cursor-pointer">
      <input
        checked={checked}
        onChange={onChange}
        type="checkbox"
        className="mr-2 w-3.5 h-3.5 my-auto"
      />

      <div>
        <Label small>{label}</Label>
        {sublabel && <SubLabel>{sublabel}</SubLabel>}
      </div>
    </label>
  );
}

function Selector({
  label,
  subtext,
  options,
  selected,
  onSelect,
}: {
  label: string;
  subtext: string;
  options: Option<string>[];
  selected: string;
  onSelect: (value: string | number | null) => void;
}) {
  return (
    <div className="mb-8">
      {label && <Label>{label}</Label>}
      {subtext && <SubLabel>{subtext}</SubLabel>}

      <div className="mt-2 w-full max-w-96">
        <DefaultDropdown
          options={options}
          selected={selected}
          onSelect={onSelect}
        />
      </div>
    </div>
  );
}

function IntegerInput({
  label,
  sublabel,
  value,
  onChange,
  id,
  placeholder = "Введите число", // Default placeholder if none is provided
}: {
  label: string;
  sublabel: string;
  value: number | null;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  id?: string;
  placeholder?: string;
}) {
  return (
    <label className="flex flex-col text-sm mb-4">
      <Label>{label}</Label>
      <SubLabel>{sublabel}</SubLabel>
      <input
        type="number"
        className="mt-1 p-2 border rounded w-full max-w-xs"
        value={value ?? ""}
        onChange={onChange}
        min="1"
        step="1"
        id={id}
        placeholder={placeholder}
      />
    </label>
  );
}

export function SettingsForm() {
  const router = useRouter();
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [chatRetention, setChatRetention] = useState("");
  const { popup, setPopup } = usePopup();
  const isEnterpriseEnabled = usePaidEnterpriseFeaturesEnabled();

  // Pass setPopup to the hook
  const {
    visionProviders,
    visionLLM,
    setVisionLLM,
    updateDefaultVisionProvider,
  } = useVisionProviders(setPopup);

  const combinedSettings = useContext(SettingsContext);

  useEffect(() => {
    if (combinedSettings) {
      setSettings(combinedSettings.settings);
      setChatRetention(
        combinedSettings.settings.maximum_chat_retention_days?.toString() || ""
      );
    }
    // We don't need to fetch vision providers here anymore as the hook handles it
  }, []);

  if (!settings) {
    return null;
  }

  const { data, error, mutate } = useSWR<{ token: string }>(
    "/api/telegram/token",
    errorHandlingFetcher
  );

  const onChangeTelegramToken = async (value: string) => {
    const response = await fetch("/api/telegram/token", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        token: value,
      }),
    });
    if (response.ok) {
      mutate({ token: value });
      return true;
    } else {
      alert(`Ошибка обновления токена`);
      return false;
    }
  };

  async function updateSettingField(
    updateRequests: { fieldName: keyof Settings; newValue: any }[]
  ) {
    // Optimistically update the local state
    const newSettings: Settings | null = settings
      ? {
          ...settings,
          ...updateRequests.reduce((acc, { fieldName, newValue }) => {
            acc[fieldName] = newValue ?? settings[fieldName];
            return acc;
          }, {} as Partial<Settings>),
        }
      : null;
    setSettings(newSettings);

    try {
      const response = await fetch("/api/admin/settings", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(newSettings),
      });

      if (!response.ok) {
        const errorMsg = (await response.json()).detail;
        throw new Error(errorMsg);
      }

      router.refresh();
      setPopup({
        message: "Настройки обновлены успешно!",
        type: "success",
      });
    } catch (error) {
      // Отменить оптимистичное обновление
      setSettings(settings);
      console.error("Ошибка обновления настроек:", error);
      setPopup({
        message: `Не удалось обновить настройки`,
        type: "error",
      });
    }
  }

  function handleToggleSettingsField(
    fieldName: keyof Settings,
    checked: boolean
  ) {
    if (fieldName === "anonymous_user_enabled" && checked) {
      setShowConfirmModal(true);
    } else {
      const updates: { fieldName: keyof Settings; newValue: any }[] = [
        { fieldName, newValue: checked },
      ];

      updateSettingField(updates);
    }
  }

  function handleConfirmAnonymousUsers() {
    const updates: { fieldName: keyof Settings; newValue: any }[] = [
      { fieldName: "anonymous_user_enabled", newValue: true },
    ];
    updateSettingField(updates);
    setShowConfirmModal(false);
  }

  function handleSetChatRetention() {
    const newValue = chatRetention === "" ? null : parseInt(chatRetention, 10);
    updateSettingField([
      { fieldName: "maximum_chat_retention_days", newValue },
    ]);
  }

  function handleClearChatRetention() {
    setChatRetention("");
    updateSettingField([
      { fieldName: "maximum_chat_retention_days", newValue: null },
    ]);
  }

  return (
    <div className="flex flex-col pb-8">
      {popup}
      <Title className="mb-4">{i18n.t(k.WORKSPACE_SETTINGS)}</Title>
      <Checkbox
        label="Автопрокрутка"
        sublabel="Если установлено, окно чата будет автоматически прокручиваться вниз по мере генерации новых строк текста моделью ИИ. Это можно переопределить индивидуальными настройками пользователя."
        checked={settings.auto_scroll}
        onChange={(e) =>
          handleToggleSettingsField("auto_scroll", e.target.checked)
        }
      />

      <Checkbox
        label="Переопределить температуру по умолчанию"
        sublabel="Если установлено, пользователи смогут переопределить температуру по умолчанию для каждого помощника."
        checked={settings.temperature_override_enabled}
        onChange={(e) =>
          handleToggleSettingsField(
            "temperature_override_enabled",
            e.target.checked
          )
        }
      />

      <Checkbox
        label="Анонимные пользователи"
        sublabel="Если установлено, пользователям не потребуется входить в систему для использования SmartSearch."
        checked={settings.anonymous_user_enabled}
        onChange={(e) =>
          handleToggleSettingsField("anonymous_user_enabled", e.target.checked)
        }
      />

      <Checkbox
        label="Поиск агента"
        sublabel="Если установлено, пользователи смогут использовать Поиск агента."
        checked={settings.pro_search_enabled ?? true}
        onChange={(e) =>
          handleToggleSettingsField("pro_search_enabled", e.target.checked)
        }
      />

      {NEXT_PUBLIC_CLOUD_ENABLED && settings.anonymous_user_enabled && (
        <AnonymousUserPath setPopup={setPopup} />
      )}
      {showConfirmModal && (
        <Modal
          width="max-w-3xl w-full"
          onOutsideClick={() => setShowConfirmModal(false)}
        >
          <div className="flex flex-col gap-4">
            <h2 className="text-xl font-bold">
              {i18n.t(k.ENABLE_ANONYMOUS_USERS)}
            </h2>
            <p>{i18n.t(k.ARE_YOU_SURE_YOU_WANT_TO_ENABL)}</p>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setShowConfirmModal(false)}
              >
                {i18n.t(k.CANCEL)}
              </Button>
              <Button onClick={handleConfirmAnonymousUsers}>
                {i18n.t(k.CONFIRM)}
              </Button>
            </div>
          </div>
        </Modal>
      )}
      {isEnterpriseEnabled && (
        <>
          <Title className="mt-8 mb-4">{i18n.t(k.CHAT_SETTINGS)}</Title>
          <IntegerInput
            label="Сохранение чата"
            sublabel="Введите максимальное количество дней, в течение которых SmartSearch будет хранить сообщения чата. Если оставить это поле пустым, SmartSearch никогда не удалит сообщения чата."
            value={chatRetention === "" ? null : Number(chatRetention)}
            onChange={(e) => {
              const numValue = parseInt(e.target.value, 10);
              if (numValue >= 1 || e.target.value === "") {
                setChatRetention(e.target.value);
              }
            }}
            id="chatRetentionInput"
            placeholder="Бесконечное удержание"
          />

          <div className="mr-auto flex gap-2">
            <Button
              onClick={handleSetChatRetention}
              variant="submit"
              size="sm"
              className="mr-auto"
            >
              {i18n.t(k.SET_RETENTION_LIMIT)}
            </Button>
            <Button
              onClick={handleClearChatRetention}
              variant="default"
              size="sm"
              className="mr-auto"
            >
              {i18n.t(k.RETAIN_ALL)}
            </Button>
          </div>
        </>
      )}

      {/* Image Processing Settings */}
      <Title className="mt-8 mb-4">{i18n.t(k.IMAGE_PROCESSING)}</Title>

      <div className="flex flex-col gap-2">
        <Checkbox
          label="Включить извлечение и анализ изображений"
          sublabel="Извлекать и анализировать изображения из документов во время индексации. Это позволяет системе обрабатывать изображения и создавать их описания с возможностью поиска."
          checked={settings.image_extraction_and_analysis_enabled ?? false}
          onChange={(e) =>
            handleToggleSettingsField(
              "image_extraction_and_analysis_enabled",
              e.target.checked
            )
          }
        />

        <Checkbox
          label="Включить анализ изображений во время поиска"
          sublabel="Анализировать изображения во время поиска, когда пользователь спрашивает об изображениях. Это обеспечивает более подробный и специфичный для запроса анализ изображений, но может увеличить задержку во время поиска."
          checked={settings.search_time_image_analysis_enabled ?? false}
          onChange={(e) =>
            handleToggleSettingsField(
              "search_time_image_analysis_enabled",
              e.target.checked
            )
          }
        />

        <IntegerInput
          label="Максимальный размер изображения для анализа (МБ)"
          sublabel="Изображения больше этого размера не будут анализироваться, чтобы предотвратить чрезмерное использование ресурсов."
          value={settings.image_analysis_max_size_mb ?? null}
          onChange={(e) => {
            const value = e.target.value ? parseInt(e.target.value) : null;
            if (value !== null && !isNaN(value) && value > 0) {
              updateSettingField([
                { fieldName: "image_analysis_max_size_mb", newValue: value },
              ]);
            }
          }}
          id="image-analysis-max-size"
          placeholder="Введите максимальный размер в МБ"
        />

        {/* Default Vision LLM Section */}
        <div className="mt-4">
          <Label>{i18n.t(k.DEFAULT_VISION_LLM)}</Label>
          <SubLabel>{i18n.t(k.SELECT_THE_DEFAULT_LLM_TO_USE)}</SubLabel>

          <div className="mt-2 max-w-xs">
            {!visionProviders || visionProviders.length === 0 ? (
              <div className="text-sm text-gray-500">
                {i18n.t(k.NO_VISION_PROVIDERS_FOUND_PLE)}
              </div>
            ) : visionProviders.length > 0 ? (
              <>
                <LLMSelector
                  userSettings={false}
                  llmProviders={visionProviders.map((provider) => ({
                    ...provider,
                    model_names: provider.vision_models,
                    display_model_names: provider.vision_models,
                  }))}
                  currentLlm={visionLLM}
                  onSelect={(value) => setVisionLLM(value)}
                />

                <Button
                  onClick={() => updateDefaultVisionProvider(visionLLM)}
                  className="mt-2"
                  variant="default"
                  size="sm"
                >
                  {i18n.t(k.SET_DEFAULT_VISION_LLM)}
                </Button>
              </>
            ) : (
              <div className="text-sm text-gray-500">
                {i18n.t(k.NO_VISION_CAPABLE_LLMS_FOUND)}
              </div>
            )}
          </div>
        </div>

        <Title className="mb-4 mt-6">Интеграция Telegram</Title>
        <div className="block font-medium text-base">Токен Telegram-бота:</div>
        <div className="w-fit">
          <EditableValue
            initialValue={error ? error.detail : data?.token}
            onSubmit={onChangeTelegramToken}
            consistentWidth={false}
          />
        </div>
      </div>
    </div>
  );
}
