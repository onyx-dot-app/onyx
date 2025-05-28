'use client';

import React, { useState } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';

interface TiptapEditorProps {
  content?: string;
  onChange?: (content: string) => void;
  editable?: boolean;
}

export function TiptapEditor({ content = '', onChange, editable = true }: TiptapEditorProps) {
  const editor = useEditor({
    extensions: [StarterKit],
    content,
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
            onClick={() => editor.chain().focus().toggleBold().run()}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${editor.isActive('bold') ? 'bg-accent text-accent-foreground' : 'bg-background border border-border hover:bg-accent/50'}`}
          >
            Bold
          </button>
          <button
            onClick={() => editor.chain().focus().toggleItalic().run()}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${editor.isActive('italic') ? 'bg-accent text-accent-foreground' : 'bg-background border border-border hover:bg-accent/50'}`}
          >
            Italic
          </button>
          <button
            onClick={() => editor.chain().focus().toggleStrike().run()}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${editor.isActive('strike') ? 'bg-accent text-accent-foreground' : 'bg-background border border-border hover:bg-accent/50'}`}
          >
            Strikethrough
          </button>
          <button
            onClick={() => editor.chain().focus().toggleCode().run()}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${editor.isActive('code') ? 'bg-accent text-accent-foreground' : 'bg-background border border-border hover:bg-accent/50'}`}
          >
            Code
          </button>
          <button
            onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${editor.isActive('heading', { level: 1 }) ? 'bg-accent text-accent-foreground' : 'bg-background border border-border hover:bg-accent/50'}`}
          >
            H1
          </button>
          <button
            onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${editor.isActive('heading', { level: 2 }) ? 'bg-accent text-accent-foreground' : 'bg-background border border-border hover:bg-accent/50'}`}
          >
            H2
          </button>
          <button
            onClick={() => editor.chain().focus().toggleBulletList().run()}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${editor.isActive('bulletList') ? 'bg-accent text-accent-foreground' : 'bg-background border border-border hover:bg-accent/50'}`}
          >
            Bullet List
          </button>
          <button
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${editor.isActive('orderedList') ? 'bg-accent text-accent-foreground' : 'bg-background border border-border hover:bg-accent/50'}`}
          >
            Numbered List
          </button>
          <button
            onClick={() => editor.chain().focus().toggleBlockquote().run()}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${editor.isActive('blockquote') ? 'bg-accent text-accent-foreground' : 'bg-background border border-border hover:bg-accent/50'}`}
          >
            Quote
          </button>
        </div>
      )}
      <EditorContent 
        editor={editor} 
        className="prose prose-sm max-w-none focus:outline-none min-h-[200px] [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mb-4 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:mb-3 [&_p]:mb-2 [&_ul]:ml-4"
      />
    </div>
  );
}
