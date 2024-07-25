"use client";

import { Label, SubLabel } from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Title } from "@tremor/react";
import { Settings } from "./interfaces";
import { useRouter } from "next/navigation";
import { DefaultDropdown, Option } from "@/components/Dropdown";
import { useContext } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import React, { useState, useEffect } from "react";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { Button } from "@tremor/react";

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
  const combinedSettings = useContext(SettingsContext);
  const [chatRetention, setChatRetention] = useState("");
  const { popup, setPopup } = usePopup();
  const isEnterpriseEnabled = usePaidEnterpriseFeaturesEnabled();

  useEffect(() => {
    if (combinedSettings?.settings.maximum_chat_retention_days !== undefined) {
      setChatRetention(
        combinedSettings.settings.maximum_chat_retention_days?.toString() || ""
      );
    }
  }, [combinedSettings?.settings.maximum_chat_retention_days]);

  if (!combinedSettings) {
    return null;
  }
  const settings = combinedSettings.settings;

  async function updateSettingField(
    updateRequests: { fieldName: keyof Settings; newValue: any }[]
  ) {
    const newValues: any = {};
    updateRequests.forEach(({ fieldName, newValue }) => {
      newValues[fieldName] = newValue;
    });

    const response = await fetch("/api/admin/settings", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...settings,
        ...newValues,
      }),
    });
    if (response.ok) {
      router.refresh();
    } else {
      const errorMsg = (await response.json()).detail;
      alert(`Failed to update settings. ${errorMsg}`);
    }
  }

  function handleSetChatRetention() {
    // Convert chatRetention to a number or null and update the global settings
    const newValue =
      chatRetention === "" ? null : parseInt(chatRetention.toString(), 10);
    updateSettingField([
      { fieldName: "maximum_chat_retention_days", newValue: newValue },
    ])
      .then(() => {
        setPopup({
          message: "Chat retention settings updated successfully!",
          type: "success",
        });
      })
      .catch((error) => {
        console.error("Error updating settings:", error);
        const errorMessage =
          error.response?.data?.message || error.message || "Unknown error";
        setPopup({
          message: `Failed to update settings: ${errorMessage}`,
          type: "error",
        });
      });
  }

  function handleClearChatRetention() {
    setChatRetention(""); // Clear the chat retention input
    updateSettingField([
      { fieldName: "maximum_chat_retention_days", newValue: null },
    ]).then(() => {
      setPopup({
        message: "Chat retention cleared successfully!",
        type: "success",
      });
    });
  }

  return (
    <div>
      {popup}
      <Title className="mb-4">Page Visibility</Title>

      <Checkbox
        label="Search Page Enabled?"
        sublabel={`If set, then the "Search" page will be accessible to all users 
        and will show up as an option on the top navbar. If unset, then this 
        page will not be available.`}
        checked={settings.search_page_enabled}
        onChange={(e) => {
          const updates: any[] = [
            { fieldName: "search_page_enabled", newValue: e.target.checked },
          ];
          if (!e.target.checked && settings.default_page === "search") {
            updates.push({ fieldName: "default_page", newValue: "chat" });
          }
          updateSettingField(updates);
        }}
      />

      <Checkbox
        label="Chat Page Enabled?"
        sublabel={`If set, then the "Chat" page will be accessible to all users 
        and will show up as an option on the top navbar. If unset, then this 
        page will not be available.`}
        checked={settings.chat_page_enabled}
        onChange={(e) => {
          const updates: any[] = [
            { fieldName: "chat_page_enabled", newValue: e.target.checked },
          ];
          if (!e.target.checked && settings.default_page === "chat") {
            updates.push({ fieldName: "default_page", newValue: "search" });
          }
          updateSettingField(updates);
        }}
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
              if (numValue >= 1) {
                setChatRetention(numValue.toString());
              } else if (e.target.value === "") {
                setChatRetention("");
              }
            }}
            id="chatRetentionInput"
            placeholder="Infinite Retention"
          />
          <Button
            onClick={handleSetChatRetention}
            color="green"
            size="xs"
            className="mr-3"
          >
            Set Retention Limit
          </Button>
          <Button onClick={handleClearChatRetention} color="blue" size="xs">
            Retain All
          </Button>
        </>
      )}
    </div>
  );
}
