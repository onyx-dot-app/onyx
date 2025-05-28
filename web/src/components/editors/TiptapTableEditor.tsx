'use client';

import React, { useState } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Table from '@tiptap/extension-table';
import TableRow from '@tiptap/extension-table-row';
import TableHeader from '@tiptap/extension-table-header';
import TableCell from '@tiptap/extension-table-cell';

interface TiptapTableEditorProps {
  content?: string;
  onChange?: (content: string) => void;
  editable?: boolean;
}

export function TiptapTableEditor({ content, onChange, editable = true }: TiptapTableEditorProps) {
  const defaultContent = content || `
    <table>
      <tbody>
        <tr>
          <th>Constant Name</th>
          <th>Value</th>
          <th>Description</th>
        </tr>
        <tr>
          <td>API_BASE_URL</td>
          <td>https://api.example.com</td>
          <td>Base URL for API endpoints</td>
        </tr>
        <tr>
          <td>MAX_RETRIES</td>
          <td>3</td>
          <td>Maximum number of retry attempts</td>
        </tr>
        <tr>
          <td>TIMEOUT_MS</td>
          <td>5000</td>
          <td>Request timeout in milliseconds</td>
        </tr>
      </tbody>
    </table>
  `;

  const editor = useEditor({
    extensions: [
      StarterKit,
      Table.configure({
        resizable: true,
      }),
      TableRow,
      TableHeader,
      TableCell,
    ],
    content: defaultContent,
    editable,
    onUpdate: ({ editor }) => {
      onChange?.(editor.getHTML());
    },
  });

  if (!editor) {
    return null;
  }

  return (
    <div className="border border-border rounded-lg p-6 bg-background shadow-sm">
      {editable && (
        <div className="mb-6 flex gap-2 flex-wrap pb-4 border-b border-border">
          <button
            onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}
            className="px-4 py-2 rounded-md text-sm font-medium bg-background border border-border hover:bg-accent/50 transition-colors"
          >
            Insert Table
          </button>
          <button
            onClick={() => editor.chain().focus().addRowBefore().run()}
            className="px-4 py-2 rounded-md text-sm font-medium bg-background border border-border hover:bg-accent/50 transition-colors"
          >
            Add Row Before
          </button>
          <button
            onClick={() => editor.chain().focus().addRowAfter().run()}
            className="px-4 py-2 rounded-md text-sm font-medium bg-background border border-border hover:bg-accent/50 transition-colors"
          >
            Add Row After
          </button>
          <button
            onClick={() => editor.chain().focus().deleteRow().run()}
            className="px-4 py-2 rounded-md text-sm font-medium bg-background border border-border hover:bg-accent/50 transition-colors"
          >
            Delete Row
          </button>
          <button
            onClick={() => editor.chain().focus().addColumnBefore().run()}
            className="px-4 py-2 rounded-md text-sm font-medium bg-background border border-border hover:bg-accent/50 transition-colors"
          >
            Add Column Before
          </button>
          <button
            onClick={() => editor.chain().focus().addColumnAfter().run()}
            className="px-4 py-2 rounded-md text-sm font-medium bg-background border border-border hover:bg-accent/50 transition-colors"
          >
            Add Column After
          </button>
          <button
            onClick={() => editor.chain().focus().deleteColumn().run()}
            className="px-4 py-2 rounded-md text-sm font-medium bg-background border border-border hover:bg-accent/50 transition-colors"
          >
            Delete Column
          </button>
        </div>
      )}
      <EditorContent 
        editor={editor} 
        className="prose prose-sm max-w-none focus:outline-none min-h-[300px] [&_table]:border-collapse [&_table]:border-2 [&_table]:border-border [&_th]:border-2 [&_th]:border-border [&_th]:bg-accent [&_th]:p-2 [&_td]:border-2 [&_td]:border-border [&_td]:p-2 [&_td]:bg-background"
      />
    </div>
  );
}
