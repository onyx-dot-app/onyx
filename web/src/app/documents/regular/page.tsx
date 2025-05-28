'use client';

import React, { useState } from 'react';
import { TiptapEditor } from '../../../components/editors/TiptapEditor';
import { DocumentLayout } from '@/components/layout/DocumentLayout';

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

  return (
    <DocumentLayout>
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
