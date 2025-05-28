'use client';

import React, { useState, useEffect } from 'react';
import { TiptapEditor } from '../../../components/editors/TiptapEditor';
import { DocumentLayout } from '@/components/layout/DocumentLayout';
import { CombinedSettings } from '@/app/admin/settings/interfaces';
import { ApplicationStatus, QueryHistoryType } from '@/app/admin/settings/interfaces';

export default function RegularDocumentPage() {
  const [content, setContent] = useState(`
    <h1>Welcome to Onyx Document Editor</h1>
    <p>This is a regular document editor powered by Tiptap. You can:</p>
    <ul>
      <li>Format text with <strong>bold</strong> and <em>italic</em></li>
      <li>Create headings and lists</li>
      <li>Write and edit rich content</li>
    </ul>
    <p>Start editing to see the editor in action!</p>
  `);

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
      <div className="container mx-auto p-6 max-w-4xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-foreground mb-2">Regular Document</h1>
          <p className="text-muted-foreground">A rich text editor for creating and editing documents</p>
        </div>
        
        <TiptapEditor 
          content={content}
          onChange={setContent}
        />
      </div>
    </DocumentLayout>
  );
}
