'use client';

import React, { useState } from 'react';
import { TiptapTableEditor } from '../../../components/editors/TiptapTableEditor';
import { DocumentLayout } from '@/components/layout/DocumentLayout';

export default function ConstantsDocumentPage() {
  const [content, setContent] = useState('');

  return (
    <DocumentLayout>
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
