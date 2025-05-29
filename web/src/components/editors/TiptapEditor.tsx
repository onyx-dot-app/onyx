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
  const editor = useEditor({
    extensions: [
      StarterKit,
      HighlightWithLink,
    ],
    content,
    editable,
    onUpdate: ({ editor }) => {
      onChange?.(editor.getHTML());
    },
  }, [content]); // Add content as dependency to reinitialize when content changes

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
