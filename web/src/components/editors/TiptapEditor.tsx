'use client';

import React from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Superscript from '@tiptap/extension-superscript';
import Subscript from '@tiptap/extension-subscript';
import TextAlign from '@tiptap/extension-text-align';
import Link from '@tiptap/extension-link';
import Table from '@tiptap/extension-table';
import TableRow from '@tiptap/extension-table-row';
import TableCell from '@tiptap/extension-table-cell';
import TableHeader from '@tiptap/extension-table-header';

import { DeletionMark, AdditionMark } from '@/lib/tiptap/DiffMarks';
import { CitationMark, CitationBubbleMenu } from '@/lib/tiptap/CitationMark';
import { DocumentBase, FormattedDocumentBase } from '@/lib/hooks/useGoogleDocs';
import { FormattingToolbar } from './FormattingToolbar';

interface TiptapEditorProps {
  content?: string;
  documentData?: DocumentBase | FormattedDocumentBase | null;
  onChange?: (content: string) => void;
  editable?: boolean;
}

export function TiptapEditor({ content = '', documentData, onChange, editable = true }: TiptapEditorProps) {
  // Track document ID to know when to update content
  const docIdRef = React.useRef<string | null>(documentData?.id || null);

  const editor = useEditor({
    extensions: [
      StarterKit,
      DeletionMark,
      AdditionMark,
      Superscript,
      Subscript,
      TextAlign.configure({
        types: ['heading', 'paragraph'],
      }),
      Link.configure({
        openOnClick: false,
      }),
      Table.configure({
        resizable: true,
      }),
      TableRow,
      TableHeader,
      TableCell,
      CitationMark,
    ],
    content, // Initialize with provided content
    editable,
    onUpdate: ({ editor }) => {
      // Only call onChange if it's a user-triggered update
      onChange?.(editor.getHTML());
    },
    editorProps: {
      attributes: {
        class: 'focus:outline-none p-4',
      },
    },
  });

  // Update content when switching documents but preserve during typing
  React.useEffect(() => {
    const currentDocId = documentData?.id || null;

    // Only update content when document ID changes (switching documents)
    if (editor) {
      editor.commands.setContent(content);
      docIdRef.current = currentDocId;
    }
  }, [editor, content, documentData])

  if (!editor) {
    return null;
  }

  return (
    <div className="editor-container">
      <style jsx global>{`
        .editor-container {
          border: 1px solid #e5e7eb;
          border-radius: 0.5rem;
          overflow: hidden;
        }
        
        .editor-content {
          padding: 1rem;
          min-height: 200px;
        }
        
        /* Existing marks */
        deletion-mark {
          text-decoration: line-through;
          color: #b91c1c;
        }
        
        addition-mark {
          color: #15803d;
          font-weight: 500;
        }

        /* Table styles */
        .editor-content table {
          border-collapse: collapse;
          margin: 1rem 0;
          overflow: hidden;
          width: 100%;
          table-layout: fixed;
        }

        .editor-content table td,
        .editor-content table th {
          border: 1px solid #e5e7eb;
          padding: 0.5rem;
          position: relative;
          vertical-align: top;
        }

        .editor-content table th {
          background-color: #f9fafb;
          font-weight: 600;
        }

        .editor-content table tr:nth-child(even) {
          background-color: #f9fafb;
        }

        /* Dark mode table styles */
        .dark .editor-content table td,
        .dark .editor-content table th {
          border: 1px solid #374151;
          background-color: #000000;
          color: #ffffff;
        }

        /* Blockquote styles */
        .editor-content blockquote {
          border-left: 3px solid #e5e7eb;
          padding-left: 1rem;
          margin-left: 0;
          margin-right: 0;
          font-style: italic;
          color: #6b7280;
        }

        /* List styles */
        .editor-content ul {
          list-style-type: disc;
          padding-left: 1.5rem;
          margin: 0.5rem 0;
        }

        .editor-content ol {
          list-style-type: decimal;
          padding-left: 1.5rem;
          margin: 0.5rem 0;
        }

        /* Medical-specific styles */
        .editor-content sup {
          font-size: 0.75em;
          line-height: 0;
          position: relative;
          vertical-align: baseline;
          top: -0.5em;
        }

        .editor-content sub {
          font-size: 0.75em;
          line-height: 0;
          position: relative;
          vertical-align: baseline;
          bottom: -0.25em;
        }

        /* Link styles */
        .editor-content a {
          color: #3b82f6;
          text-decoration: underline;
          cursor: pointer;
        }

        /* Ensure citation marks have no background styling */
        .editor-content span[data-citation] {
          background: none !important;
          background-color: transparent !important;
          padding: 0 !important;
          border: none !important;
        }

        /* Remove old citation link styles - now using bubble menu */
        /* Citation styling is now handled by the CitationMark extension */

        /* Text alignment */
        .editor-content .text-left {
          text-align: left;
        }

        .editor-content .text-center {
          text-align: center;
        }

        .editor-content .text-right {
          text-align: right;
        }
      `}</style>
      {editor && <FormattingToolbar editor={editor} />}
      {editor && <CitationBubbleMenu editor={editor} />}
      <EditorContent
        editor={editor}
        className="editor-content prose dark:prose-invert prose-sm max-w-none [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mb-4 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:mb-3 [&_p]:mb-2 [&_ul]:ml-4"
      />
    </div>
  );
}
