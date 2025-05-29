'use client';

import React, { useState, useEffect } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Table from '@tiptap/extension-table';
import TableRow from '@tiptap/extension-table-row';
import TableHeader from '@tiptap/extension-table-header';
import TableCell from '@tiptap/extension-table-cell';
import Link from '@tiptap/extension-link';
import { HighlightWithLink } from '@/lib/tiptap/HighlightWithLink';

interface TiptapTableEditorProps {
  content?: string;
  onChange?: (content: string) => void;
  editable?: boolean;
}

export function TiptapTableEditor({ content, onChange, editable = true }: TiptapTableEditorProps) {
  // Initialize the editor with the content as-is
  // The first row is already set as a header row in the DocumentsPage.convertSheetDataToTableHtml function
  
  // Function to make links clickable in the editor
  const enableClickableLinks = () => {
    // This runs after the editor is mounted
    setTimeout(() => {
      const editorElement = document.querySelector('.ProseMirror');
      if (editorElement) {
        // Add event listener to handle link clicks
        editorElement.addEventListener('click', (e) => {
          const target = e.target as HTMLElement;
          if (target.tagName === 'A') {
            const href = target.getAttribute('href');
            if (href) {
              window.open(href, '_blank', 'noopener,noreferrer');
            }
          }
        });
      }
    }, 100);
  };
  
  const editor = useEditor({
    extensions: [
      // Use StarterKit with default configuration
      StarterKit,
      Table.configure({
        resizable: true,
      }),
      TableRow,
      TableHeader,
      TableCell,
      Link.configure({
        openOnClick: true,
        // Make links clickable
        autolink: true,
        // Allow the editor to parse links from HTML
        linkOnPaste: true,
        // Open links in a new tab
        HTMLAttributes: {
          target: '_blank',
          rel: 'noopener noreferrer',
          class: 'text-blue-500 underline hover:text-blue-700',
        },
      }),
      HighlightWithLink,
    ],
    content: content || '',
    editable,
    onUpdate: ({ editor }) => {
      onChange?.(editor.getHTML());
    },
  }, [content]); // Add content as a dependency to re-initialize editor when content changes

  // Call enableClickableLinks when the editor is ready
  useEffect(() => {
    if (editor) {
      enableClickableLinks();
    }
  }, [editor]);

  if (!editor) {
    return null;
  }

  return (
    <div className="">
      <EditorContent 
        editor={editor} 
        className="prose prose-sm max-w-none focus:outline-none min-h-[300px] [&_table]:border-collapse [&_table]:border-2 [&_table]:border-border [&_th]:border-2 [&_th]:border-border [&_th]:bg-accent [&_th]:p-2 [&_td]:border-2 [&_td]:border-border [&_td]:p-2 [&_td]:bg-background [&_a]:text-blue-500 [&_a]:underline [&_a:hover]:text-blue-700"
      />
    </div>
  );
}
