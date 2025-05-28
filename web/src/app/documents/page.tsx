import React from 'react';
import Link from 'next/link';
import { FileIcon, TableIcon } from 'lucide-react';
import { DocumentLayout } from '@/components/layout/DocumentLayout';
import { fetchSettingsSS } from '@/components/settings/lib';

export default async function DocumentsPage() {
  const settings = await fetchSettingsSS();
  
  return (
    <DocumentLayout settings={settings || undefined}>
      <div className="container mx-auto p-6 max-w-4xl">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-foreground mb-2">Documents</h1>
          <p className="text-muted-foreground">Choose a document type to get started</p>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Link 
            href="/documents/regular"
            className="block p-6 border border-border rounded-lg hover:shadow-md transition-shadow"
          >
            <div className="flex items-center mb-4">
              <FileIcon className="h-8 w-8 text-primary mr-3" />
              <h2 className="text-xl font-semibold">Regular Document</h2>
            </div>
            <p className="text-muted-foreground">
              Create and edit rich text documents with formatting, headings, and lists.
            </p>
          </Link>
          
          <Link 
            href="/documents/constants"
            className="block p-6 border border-border rounded-lg hover:shadow-md transition-shadow"
          >
            <div className="flex items-center mb-4">
              <TableIcon className="h-8 w-8 text-primary mr-3" />
              <h2 className="text-xl font-semibold">Constants Spreadsheet</h2>
            </div>
            <p className="text-muted-foreground">
              Manage application constants in a structured table format.
            </p>
          </Link>
        </div>
      </div>
    </DocumentLayout>
  );
}
