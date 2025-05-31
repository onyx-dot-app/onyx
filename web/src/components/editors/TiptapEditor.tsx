'use client';

import React from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { HighlightWithLink } from '@/lib/tiptap/HighlightWithLink';
import { DocumentBase } from '@/lib/hooks/useGoogleDocs';

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
      HighlightWithLink,
    ],
    content, // Initialize with provided content
    editable,
    onUpdate: ({ editor }) => {
      // Only call onChange if it's a user-triggered update
      onChange?.(editor.getHTML());
    },
  });
  
  // Update content when switching documents but preserve during typing
  React.useEffect(() => {
    const currentDocId = documentData?.id || null;
    
    // Only update content when document ID changes (switching documents)
    if (editor && currentDocId !== docIdRef.current) {
      editor.commands.setContent(content);
      docIdRef.current = currentDocId;
    }
  }, [editor, content, documentData])

  if (!editor) {
    return null;
  }

  return (
    <div className="border border-border rounded-lg p-6 bg-background shadow-sm">
      <EditorContent 
        editor={editor} 
        className="prose prose-sm max-w-none focus:outline-none min-h-[200px] [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mb-4 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:mb-3 [&_p]:mb-2 [&_ul]:ml-4"
      />
    </div>
  );
}
