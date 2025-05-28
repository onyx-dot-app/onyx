'use client';

import React from 'react';
import FixedLogo from '@/components/logo/FixedLogo';
import { UserDropdown } from '@/components/UserDropdown';
import { DocumentSidebar } from '@/components/documents/DocumentSidebar';
import { defaultSidebarFiles } from '@/lib/documents/types';
import { CombinedSettings, ApplicationStatus, QueryHistoryType } from '@/app/admin/settings/interfaces';
import { SettingsProvider } from '@/components/settings/SettingsProvider';

interface DocumentLayoutProps {
  children: React.ReactNode;
  settings?: CombinedSettings;
}

export function DocumentLayout({ children, settings }: DocumentLayoutProps) {
  const defaultSettings: CombinedSettings = {
    settings: {
      auto_scroll: true,
      application_status: ApplicationStatus.ACTIVE,
      gpu_enabled: false,
      maximum_chat_retention_days: null,
      notifications: [],
      needs_reindexing: false,
      anonymous_user_enabled: false,
      pro_search_enabled: true,
      temperature_override_enabled: true,
      query_history_type: QueryHistoryType.NORMAL,
    },
    enterpriseSettings: null,
    customAnalyticsScript: null,
    webVersion: 'local',
    webDomain: 'localhost',
  };

  const content = (
    <div className="relative min-h-screen bg-background">
      {/* Fixed Logo */}
      <FixedLogo backgroundToggled={false} />
      
      {/* User Dropdown in top right */}
      <div className="fixed top-3 right-4 z-40">
        <UserDropdown page="documents" />
      </div>
      
      {/* Main content with sidebar */}
      <div className="flex h-screen pt-16">
        {/* Sidebar */}
        <div className="flex-none w-[250px]">
          <DocumentSidebar files={defaultSidebarFiles} />
        </div>
        
        {/* Content */}
        <div className="flex-grow overflow-auto">
          {children}
        </div>
      </div>
    </div>
  );

  return settings ? (
    <SettingsProvider settings={settings}>
      {content}
    </SettingsProvider>
  ) : (
    <SettingsProvider settings={defaultSettings}>
      {content}
    </SettingsProvider>
  );
}
