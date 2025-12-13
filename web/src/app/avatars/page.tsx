"use client";

import React, { useState, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { AvatarQueryPanel } from "./components/AvatarQueryPanel";
import { AvatarSettings } from "./components/AvatarSettings";
import { PermissionRequests } from "./components/PermissionRequests";
import { Search, Settings, Bell, Users } from "lucide-react";

type TabType = "query" | "requests" | "settings";

function isValidTab(tab: string | null): tab is TabType {
  return tab === "query" || tab === "requests" || tab === "settings";
}

export default function AvatarsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const tabParam = searchParams.get("tab");
  const initialTab = isValidTab(tabParam) ? tabParam : "query";
  const [activeTab, setActiveTab] = useState<TabType>(initialTab);

  // Sync URL when tab changes
  const handleTabChange = (tab: TabType) => {
    setActiveTab(tab);
    router.replace(`/avatars?tab=${tab}`, { scroll: false });
  };

  // Update state if URL changes externally
  useEffect(() => {
    if (isValidTab(tabParam) && tabParam !== activeTab) {
      setActiveTab(tabParam);
    }
  }, [tabParam, activeTab]);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-4xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <Users className="h-8 w-8 text-accent" />
            <h1 className="text-2xl font-bold">Avatars</h1>
          </div>
          <p className="text-text-subtle">
            Query other users' knowledge bases or manage your own avatar
            settings
          </p>
        </div>

        {/* Navigation Tabs */}
        <div className="flex border-b border-border mb-6">
          <button
            onClick={() => handleTabChange("query")}
            className={`flex items-center gap-2 px-4 py-3 border-b-2 transition-colors ${
              activeTab === "query"
                ? "border-accent text-accent"
                : "border-transparent text-text-subtle hover:text-text"
            }`}
          >
            <Search className="h-4 w-4" />
            Query Avatars
          </button>
          <button
            onClick={() => handleTabChange("requests")}
            className={`flex items-center gap-2 px-4 py-3 border-b-2 transition-colors ${
              activeTab === "requests"
                ? "border-accent text-accent"
                : "border-transparent text-text-subtle hover:text-text"
            }`}
          >
            <Bell className="h-4 w-4" />
            Permission Requests
          </button>
          <button
            onClick={() => handleTabChange("settings")}
            className={`flex items-center gap-2 px-4 py-3 border-b-2 transition-colors ${
              activeTab === "settings"
                ? "border-accent text-accent"
                : "border-transparent text-text-subtle hover:text-text"
            }`}
          >
            <Settings className="h-4 w-4" />
            My Avatar Settings
          </button>
        </div>

        {/* Tab Content */}
        <div>
          {activeTab === "query" && <AvatarQueryPanel />}
          {activeTab === "requests" && <PermissionRequests />}
          {activeTab === "settings" && <AvatarSettings />}
        </div>
      </div>
    </div>
  );
}
