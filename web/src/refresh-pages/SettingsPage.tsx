"use client";

import { useState } from "react";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import { SvgCpu, SvgSliders } from "@opal/icons";
import Card from "@/refresh-components/Card";
import * as InputLayouts from "@/layouts/input-layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import LineItem from "@/refresh-components/buttons/LineItem";

function GeneralSettings() {
  return (
    <div className="flex flex-col">
      <Card>
        <InputLayouts.Horizontal
          label="Full Name"
          description="We'll display this name in the app."
        >
          <InputTypeIn placeholder="Your name" />
        </InputLayouts.Horizontal>
        <InputLayouts.Horizontal
          label="Work Role"
          description="Share your role to better tailor responses."
        >
          <InputTypeIn placeholder="Your role" />
        </InputLayouts.Horizontal>
      </Card>

      <Card>
        <InputLayouts.Horizontal
          label="Color Mode"
          description="Select your preferred color mode for the UI."
        >
          <InputSelect>
            <InputSelect.Trigger placeholder="Light" />
            <InputSelect.Content>
              <InputSelect.Item value="System">
                <LineItem>System</LineItem>
              </InputSelect.Item>
            </InputSelect.Content>
          </InputSelect>
        </InputLayouts.Horizontal>
      </Card>
    </div>
  );
}

function ChatPreferencesSettings() {
  return <div>Chat Preferences Content</div>;
}

function AccountsAccessSettings() {
  return <div>Accounts & Access Content</div>;
}

function ConnectorsSettings() {
  return <div>Connectors Content</div>;
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState(0);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={SvgSliders} title="Settings" separator />

      <SettingsLayouts.Body>
        <div className="grid grid-cols-[auto_1fr]">
          {/* Left: Tab Navigation */}
          <div className="flex flex-col px-2 py-6 w-[12.5rem]">
            <SidebarTab
              transient={activeTab === 0}
              onClick={() => setActiveTab(0)}
            >
              General
            </SidebarTab>
            <SidebarTab
              transient={activeTab === 1}
              onClick={() => setActiveTab(1)}
            >
              Chat Preferences
            </SidebarTab>
            <SidebarTab
              transient={activeTab === 2}
              onClick={() => setActiveTab(2)}
            >
              Accounts & Access
            </SidebarTab>
            <SidebarTab
              transient={activeTab === 3}
              onClick={() => setActiveTab(3)}
            >
              Connectors
            </SidebarTab>
          </div>

          {/* Right: Tab Content */}
          <div className="px-4 py-6">
            {activeTab === 0 && <GeneralSettings />}
            {activeTab === 1 && <ChatPreferencesSettings />}
            {activeTab === 2 && <AccountsAccessSettings />}
            {activeTab === 3 && <ConnectorsSettings />}
          </div>
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
