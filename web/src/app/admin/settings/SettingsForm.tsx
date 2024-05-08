"use client";

import { Label, SubLabel } from "@/components/admin/connectors/Field";
import { Title } from "@tremor/react";
import { Settings } from "./interfaces";
import { useRouter } from "next/navigation";
import { DefaultDropdown, Option } from "@/components/Dropdown";

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
    <div>
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

export function SettingsForm({ settings }: { settings: Settings }) {
  const router = useRouter();

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

  return (
    <div>
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
    </div>
  );
}
