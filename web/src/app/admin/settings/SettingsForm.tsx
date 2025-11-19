"use client";

import { Label, SubLabel } from "@/components/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import Title from "@/components/ui/title";
import Button from "@/refresh-components/buttons/Button";
import { Settings } from "./interfaces";
import { useRouter } from "next/navigation";
import React, { useContext, useState, useEffect } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { Modal } from "@/components/Modal";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { AnonymousUserPath } from "./AnonymousUserPath";
import { LLMSelector } from "@/components/llm/LLMSelector";
import { useVisionProviders } from "./hooks/useVisionProviders";

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
        <span className="block font-medium text-text-700 dark:text-neutral-100 text-sm">
          {label}
        </span>
        {sublabel && <SubLabel>{sublabel}</SubLabel>}
      </div>
    </label>
  );
}

function IntegerInput({
  label,
  sublabel,
  value,
  onChange,
  id,
  placeholder = "Enter a number", // Default placeholder if none is provided
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
  const [companyName, setCompanyName] = useState("");
  const [companyDescription, setCompanyDescription] = useState("");
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
      setCompanyName(combinedSettings.settings.company_name || "");
      setCompanyDescription(
        combinedSettings.settings.company_description || ""
      );
    }
    // We don't need to fetch vision providers here anymore as the hook handles it
  }, []);

  if (!settings) {
    return null;
  }

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
        message: "Settings updated successfully!",
        type: "success",
      });
    } catch (error) {
      // Revert the optimistic update
      setSettings(settings);
      console.error("Error updating settings:", error);
      setPopup({
        message: `Failed to update settings`,
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

  function handleCompanyNameBlur() {
    const originalValue = settings?.company_name || "";
    if (companyName !== originalValue) {
      updateSettingField([
        { fieldName: "company_name", newValue: companyName || null },
      ]);
    }
  }

  function handleCompanyDescriptionBlur() {
    const originalValue = settings?.company_description || "";
    if (companyDescription !== originalValue) {
      updateSettingField([
        {
          fieldName: "company_description",
          newValue: companyDescription || null,
        },
      ]);
    }
  }

  return (
    <div className="flex flex-col pb-8">
      {popup}
      <Title className="mb-4">Workspace Settings</Title>
      <label className="flex flex-col text-sm mb-4">
        <Label>Company Name</Label>
        <SubLabel>
          Set the company name used for search and chat context.
        </SubLabel>
        <input
          type="text"
          className="mt-1 p-2 border rounded w-full max-w-xl"
          value={companyName}
          onChange={(e) => setCompanyName(e.target.value)}
          onBlur={handleCompanyNameBlur}
          placeholder="Enter company name"
        />
      </label>

      <label className="flex flex-col text-sm mb-4">
        <Label>Company Description</Label>
        <SubLabel>
          Provide a short description of the company for search and chat
          context.
        </SubLabel>
        <textarea
          className="mt-1 p-2 border rounded w-full max-w-xl"
          value={companyDescription}
          onChange={(e) => setCompanyDescription(e.target.value)}
          onBlur={handleCompanyDescriptionBlur}
          placeholder="Enter company description"
          rows={4}
        />
      </label>

      <Checkbox
        label="Auto-scroll"
        sublabel="If set, the chat window will automatically scroll to the bottom as new lines of text are generated by the AI model. This can be overridden by individual user settings."
        checked={settings.auto_scroll}
        onChange={(e) =>
          handleToggleSettingsField("auto_scroll", e.target.checked)
        }
      />
      <Checkbox
        label="Override default temperature"
        sublabel="If set, users will be able to override the default temperature for each assistant."
        checked={settings.temperature_override_enabled}
        onChange={(e) =>
          handleToggleSettingsField(
            "temperature_override_enabled",
            e.target.checked
          )
        }
      />
      <Checkbox
        label="Anonymous Users"
        sublabel="If set, users will not be required to sign in to use Onyx."
        checked={settings.anonymous_user_enabled}
        onChange={(e) =>
          handleToggleSettingsField("anonymous_user_enabled", e.target.checked)
        }
      />

      <Checkbox
        label="Deep Research"
        sublabel="If set, users will be able to use Deep Research."
        checked={settings.deep_research_enabled ?? true}
        onChange={(e) =>
          handleToggleSettingsField("deep_research_enabled", e.target.checked)
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
            <h2 className="text-xl font-bold">Enable Anonymous Users</h2>
            <p>
              Are you sure you want to enable anonymous users? This will allow
              anyone to use Onyx without signing in.
            </p>
            <div className="flex justify-end gap-2">
              <Button secondary onClick={() => setShowConfirmModal(false)}>
                Cancel
              </Button>
              <Button onClick={handleConfirmAnonymousUsers}>Confirm</Button>
            </div>
          </div>
        </Modal>
      )}
      {isEnterpriseEnabled && (
        <>
          <Title className="mt-8 mb-4">Chat Settings</Title>
          <IntegerInput
            label="Chat Retention"
            sublabel="Enter the maximum number of days you would like Onyx to retain chat messages. Leaving this field empty will cause Onyx to never delete chat messages."
            value={chatRetention === "" ? null : Number(chatRetention)}
            onChange={(e) => {
              const numValue = parseInt(e.target.value, 10);
              if (numValue >= 1 || e.target.value === "") {
                setChatRetention(e.target.value);
              }
            }}
            id="chatRetentionInput"
            placeholder="Infinite Retention"
          />
          <div className="mr-auto flex gap-2">
            <Button onClick={handleSetChatRetention} className="mr-auto">
              Set Retention Limit
            </Button>
            <Button onClick={handleClearChatRetention} className="mr-auto">
              Retain All
            </Button>
          </div>
        </>
      )}

      {/* Image Processing Settings */}
      <Title className="mt-8 mb-4">Image Processing</Title>

      <div className="flex flex-col gap-2">
        <Checkbox
          label="Enable Image Extraction and Analysis"
          sublabel="Extract and analyze images from documents during indexing. This allows the system to process images and create searchable descriptions of them."
          checked={settings.image_extraction_and_analysis_enabled ?? false}
          onChange={(e) =>
            handleToggleSettingsField(
              "image_extraction_and_analysis_enabled",
              e.target.checked
            )
          }
        />

        <Checkbox
          label="Enable Search-time Image Analysis"
          sublabel="Analyze images at search time when a user asks about images. This provides more detailed and query-specific image analysis but may increase search-time latency."
          checked={settings.search_time_image_analysis_enabled ?? false}
          onChange={(e) =>
            handleToggleSettingsField(
              "search_time_image_analysis_enabled",
              e.target.checked
            )
          }
        />

        <IntegerInput
          label="Maximum Image Size for Analysis (MB)"
          sublabel="Images larger than this size will not be analyzed to prevent excessive resource usage."
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
          placeholder="Enter maximum size in MB"
        />
        {/* Default Vision LLM Section */}
        <div className="mt-4">
          <Label>Default Vision LLM</Label>
          <SubLabel>
            Select the default LLM to use for image analysis. This model will be
            utilized during image indexing and at query time for search results,
            if the above settings are enabled.
          </SubLabel>

          <div className="mt-2 max-w-xs">
            {!visionProviders || visionProviders.length === 0 ? (
              <div className="text-sm text-gray-500">
                No vision providers found. Please add a vision provider.
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
                >
                  Set Default Vision LLM
                </Button>
              </>
            ) : (
              <div className="text-sm text-gray-500">
                No vision-capable LLMs found. Please add an LLM provider that
                supports image input.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
