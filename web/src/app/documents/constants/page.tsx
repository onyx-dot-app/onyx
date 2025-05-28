'use client';

import React, { useState } from 'react';
import { TiptapTableEditor } from '../../../components/editors/TiptapTableEditor';
import { DocumentLayout } from '@/components/layout/DocumentLayout';
import { CombinedSettings } from '@/app/admin/settings/interfaces';
import { ApplicationStatus, QueryHistoryType } from '@/app/admin/settings/interfaces';

export default function ConstantsDocumentPage() {
  const [content, setContent] = useState('');

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

  return (
    <DocumentLayout settings={defaultSettings}>
      <div className="container mx-auto p-6 max-w-6xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-foreground mb-2">Constants Spreadsheet</h1>
          <p className="text-muted-foreground">Manage your application constants in a spreadsheet format</p>
        </div>
        
        <TiptapTableEditor 
          content={content}
          onChange={setContent}
        />
      </div>
    </DocumentLayout>
  );
}
