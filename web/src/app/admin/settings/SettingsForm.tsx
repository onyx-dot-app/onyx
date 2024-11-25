"use client";

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

function Checkbox({
  label,
  sublabel,
  checked,
  onChange,
}: {
  label: string;
  sublabel: string;
  checked: boolean;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <label className="flex text-sm mb-4">
      <input
        checked={checked}
        onChange={onChange}
        type="checkbox"
        className="mx-3 px-5 w-3.5 h-3.5 my-auto"
      />
      <div>
        <Label>{label}</Label>
        <SubLabel>{sublabel}</SubLabel>
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
  const [settings, setSettings] = useState<Settings | null>(null);
  const [chatRetention, setChatRetention] = useState("");
  const { popup, setPopup } = usePopup();
  const isEnterpriseEnabled = usePaidEnterpriseFeaturesEnabled();

  const combinedSettings = useContext(SettingsContext);

  useEffect(() => {
    if (combinedSettings) {
      setSettings(combinedSettings.settings);
      setChatRetention(
        combinedSettings.settings.maximum_chat_retention_days?.toString() || ""
      );
    }
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
    const updates: { fieldName: keyof Settings; newValue: any }[] = [
      { fieldName, newValue: checked },
    ];

    // If we're disabling a page, check if we need to update the default page
    if (
      !checked &&
      (fieldName === "search_page_enabled" || fieldName === "chat_page_enabled")
    ) {
      const otherPageField =
        fieldName === "search_page_enabled"
          ? "chat_page_enabled"
          : "search_page_enabled";
      const otherPageEnabled = settings && settings[otherPageField];

      if (
        otherPageEnabled &&
        settings?.default_page ===
          (fieldName === "search_page_enabled" ? "search" : "chat")
      ) {
        updates.push({
          fieldName: "default_page",
          newValue: fieldName === "search_page_enabled" ? "chat" : "search",
        });
      }
    }

    updateSettingField(updates);
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
    <div>
      {popup}
      <Title className="mb-4">Page Visibility</Title>

      <Checkbox
        label="Search Page Enabled?"
        sublabel="If set, then the 'Search' page will be accessible to all users and will show up as an option on the top navbar. If unset, then this page will not be available."
        checked={settings.search_page_enabled}
        onChange={(e) =>
          handleToggleSettingsField("search_page_enabled", e.target.checked)
        }
      />

      <Checkbox
        label="Chat Page Enabled?"
        sublabel="If set, then the 'Chat' page will be accessible to all users and will show up as an option on the top navbar. If unset, then this page will not be available."
        checked={settings.chat_page_enabled}
        onChange={(e) =>
          handleToggleSettingsField("chat_page_enabled", e.target.checked)
        }
      />

      <Selector
        label="Default Page"
        subtext="The page that users will be redirected to after logging in. Can only be set to a page that is enabled."
        options={[
          { value: "search", name: "Search" },
          { value: "chat", name: "Chat" },
        ]}
        selected={settings.default_page}
        onSelect={(value) => {
          value &&
            updateSettingField([
              { fieldName: "default_page", newValue: value },
            ]);
        }}
      />

      {isEnterpriseEnabled && (
        <>
          <Title className="mb-4">Chat Settings</Title>
          <IntegerInput
            label="Chat Retention"
            sublabel="Enter the maximum number of days you would like Danswer to retain chat messages. Leaving this field empty will cause Danswer to never delete chat messages."
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
          <Button
            onClick={handleSetChatRetention}
            variant="submit"
            size="sm"
            className="mr-3"
          >
            Set Retention Limit
          </Button>
          <Button
            onClick={handleClearChatRetention}
            variant="default"
            size="sm"
          >
            Retain All
          </Button>
        </>
      )}
    </div>
  );
}
