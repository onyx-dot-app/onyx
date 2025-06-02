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
import { DocumentBase } from '@/lib/hooks/useGoogleDocs';
import { FormattingToolbar } from './FormattingToolbar';

interface TiptapEditorProps {
  content?: string;
  documentData?: DocumentBase | null;
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

  // Handle citation link clicks
  React.useEffect(() => {
    if (!editor) return;

    const handleCitationClick = (event: Event) => {
      const target = event.target as HTMLElement;
      if (target.classList.contains('citation-link') || target.closest('.citation-link')) {
        event.preventDefault();
        const citationLink = target.classList.contains('citation-link') ? target : target.closest('.citation-link');
        const documentId = citationLink?.getAttribute('data-document-id');
        
        if (documentId) {
          // You can implement document preview logic here
          console.log('Citation clicked for document:', documentId);
          // Example: Show document preview modal or navigate to document
          // showDocumentPreview(documentId);
        }
      }
    };

    const editorElement = editor.view.dom;
    editorElement.addEventListener('click', handleCitationClick);

    return () => {
      editorElement.removeEventListener('click', handleCitationClick);
    };
  }, [editor]);

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

        /* Citation link styles */
        .editor-content a.citation-link {
          background-color: #fef3c7;
          border: 1px solid #f59e0b;
          border-radius: 0.25rem;
          padding: 0.125rem 0.25rem;
          color: #92400e;
          text-decoration: none;
          font-weight: 500;
          position: relative;
        }

        .editor-content a.citation-link:hover {
          background-color: #fde68a;
          border-color: #d97706;
        }

        .editor-content a.citation-link::after {
          content: "📄";
          margin-left: 0.25rem;
          font-size: 0.75em;
        }

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
      <EditorContent 
        editor={editor} 
        className="editor-content prose prose-sm max-w-none [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mb-4 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:mb-3 [&_p]:mb-2 [&_ul]:ml-4"
      />
    </div>
  );
}
