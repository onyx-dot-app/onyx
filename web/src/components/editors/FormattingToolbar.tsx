'use client';

import React from 'react';
import { Editor } from '@tiptap/react';
import { Button } from '@/components/ui/button';
import { 
  Bold, Italic, Strikethrough, Code, Heading1, Heading2, Heading3, 
  List, ListOrdered, Quote, AlignLeft, AlignCenter, AlignRight, 
  Superscript, Subscript, Table, Link, Undo, Redo, 
  PilcrowSquare, RemoveFormatting
} from 'lucide-react';

interface FormattingToolbarProps {
  editor: Editor;
}

export function FormattingToolbar({ editor }: FormattingToolbarProps) {
  if (!editor) {
    return null;
  }

  const addLink = () => {
    const url = window.prompt('URL');
    if (url) {
      editor.chain().focus().setLink({ href: url }).run();
    }
  };

  const insertTable = () => {
    editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
  };

  return (
    <div className="bg-background border border-border rounded-lg shadow-sm p-2 mb-3 overflow-x-auto">
      <div className="flex gap-1 min-w-max">
      {/* Text formatting group */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleBold().run()}
        className={editor.isActive('bold') ? 'bg-accent' : ''}
        title="Bold"
      >
        <Bold size={16} />
      </Button>
      
      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleItalic().run()}
        className={editor.isActive('italic') ? 'bg-accent' : ''}
        title="Italic"
      >
        <Italic size={16} />
      </Button>
      
      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleStrike().run()}
        className={editor.isActive('strike') ? 'bg-accent' : ''}
        title="Strikethrough"
      >
        <Strikethrough size={16} />
      </Button>
      
      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleCode().run()}
        className={editor.isActive('code') ? 'bg-accent' : ''}
        title="Inline Code"
      >
        <Code size={16} />
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleSuperscript().run()}
        className={editor.isActive('superscript') ? 'bg-accent' : ''}
        title="Superscript"
      >
        <Superscript size={16} />
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleSubscript().run()}
        className={editor.isActive('subscript') ? 'bg-accent' : ''}
        title="Subscript"
      >
        <Subscript size={16} />
      </Button>
      
      <div className="w-px bg-border mx-1" />
      
      {/* Headings group */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
        className={editor.isActive('heading', { level: 1 }) ? 'bg-accent' : ''}
        title="Heading 1"
      >
        <Heading1 size={16} />
      </Button>
      
      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        className={editor.isActive('heading', { level: 2 }) ? 'bg-accent' : ''}
        title="Heading 2"
      >
        <Heading2 size={16} />
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
        className={editor.isActive('heading', { level: 3 }) ? 'bg-accent' : ''}
        title="Heading 3"
      >
        <Heading3 size={16} />
      </Button>
      
      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().setParagraph().run()}
        className={editor.isActive('paragraph') ? 'bg-accent' : ''}
        title="Paragraph"
      >
        <PilcrowSquare size={16} />
      </Button>

      <div className="w-px bg-border mx-1" />

      {/* Lists and quotes group */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        className={editor.isActive('bulletList') ? 'bg-accent' : ''}
        title="Bullet List"
      >
        <List size={16} />
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        className={editor.isActive('orderedList') ? 'bg-accent' : ''}
        title="Numbered List"
      >
        <ListOrdered size={16} />
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
        className={editor.isActive('blockquote') ? 'bg-accent' : ''}
        title="Blockquote"
      >
        <Quote size={16} />
      </Button>

      <div className="w-px bg-border mx-1" />

      {/* Alignment group */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().setTextAlign('left').run()}
        className={editor.isActive({ textAlign: 'left' }) ? 'bg-accent' : ''}
        title="Align Left"
      >
        <AlignLeft size={16} />
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().setTextAlign('center').run()}
        className={editor.isActive({ textAlign: 'center' }) ? 'bg-accent' : ''}
        title="Align Center"
      >
        <AlignCenter size={16} />
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().setTextAlign('right').run()}
        className={editor.isActive({ textAlign: 'right' }) ? 'bg-accent' : ''}
        title="Align Right"
      >
        <AlignRight size={16} />
      </Button>

      <div className="w-px bg-border mx-1" />

      {/* Special elements group */}
      <Button
        variant="ghost"
        size="sm"
        onClick={addLink}
        className={editor.isActive('link') ? 'bg-accent' : ''}
        title="Insert Link"
      >
        <Link size={16} />
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={insertTable}
        className={editor.isActive('table') ? 'bg-accent' : ''}
        title="Insert Table"
      >
        <Table size={16} />
      </Button>

      <div className="w-px bg-border mx-1" />

      {/* History and clear formatting */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().undo().run()}
        disabled={!editor.can().undo()}
        title="Undo"
      >
        <Undo size={16} />
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().redo().run()}
        disabled={!editor.can().redo()}
        title="Redo"
      >
        <Redo size={16} />
      </Button>

      <Button
        variant="ghost"
        size="sm"
        onClick={() => editor.chain().focus().unsetAllMarks().clearNodes().run()}
        title="Clear Formatting"
      >
        <RemoveFormatting size={16} />
      </Button>
      </div>
    </div>
  );
}
