import { Mark, mergeAttributes } from '@tiptap/core';
import { BubbleMenu } from '@tiptap/react';
import React from 'react';

export interface CitationMarkOptions {
  HTMLAttributes: Record<string, any>;
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    citationMark: {
      setCitationMark: (url?: string, documentId?: string) => ReturnType;
      toggleCitationMark: (url?: string, documentId?: string) => ReturnType;
      unsetCitationMark: () => ReturnType;
    };
  }
}

export const CitationMark = Mark.create<CitationMarkOptions>({
  name: 'citationMark',

  addOptions() {
    return {
      HTMLAttributes: {},
    };
  },

  addAttributes() {
    return {
      url: {
        default: null,
        parseHTML: element => element.getAttribute('href') || element.getAttribute('data-url'),
        renderHTML: attributes => {
          if (!attributes.url) {
            return {};
          }
          return {
            'data-url': attributes.url,
          };
        },
      },
      documentId: {
        default: null,
        parseHTML: element => element.getAttribute('data-document-id'),
        renderHTML: attributes => {
          if (!attributes.documentId) {
            return {};
          }
          return {
            'data-document-id': attributes.documentId,
          };
        },
      },
    };
  },

  parseHTML() {
    return [
      // Parse old citation-link anchors
      {
        tag: 'a[class*="citation-link"]',
        getAttrs: (element) => {
          if (typeof element === 'string') return false;
          const el = element as HTMLElement;
          return {
            url: el.getAttribute('href') || el.getAttribute('data-url'),
            documentId: el.getAttribute('data-document-id'),
          };
        },
      },
      // Parse new citation-mark spans
      {
        tag: 'span[class*="citation-mark"]',
        getAttrs: (element) => {
          if (typeof element === 'string') return false;
          const el = element as HTMLElement;
          return {
            url: el.getAttribute('data-url'),
            documentId: el.getAttribute('data-document-id'),
          };
        },
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    return ['span', mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
      'data-citation': 'true',
      style: 'background: none !important; background-color: transparent !important;',
    }), 0];
  },

  addCommands() {
    return {
      setCitationMark: (url, documentId) => ({ commands }) => {
        return commands.setMark(this.name, { url, documentId });
      },
      toggleCitationMark: (url, documentId) => ({ commands }) => {
        return commands.toggleMark(this.name, { url, documentId });
      },
      unsetCitationMark: () => ({ commands }) => {
        return commands.unsetMark(this.name);
      },
    };
  },
});

interface CitationBubbleMenuProps {
  editor: any;
}

export const CitationBubbleMenu: React.FC<CitationBubbleMenuProps> = ({ editor }) => {
  if (!editor) return null;

  const handleUrlClick = () => {
    const attributes = editor.getAttributes('citationMark');
    const url = attributes.url;
    
    if (url) {
      console.log('Opening citation URL:', url);
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  };

  const getDisplayUrl = () => {
    const attributes = editor.getAttributes('citationMark');
    return attributes.url || 'Unknown document';
  };

  return (
    <BubbleMenu
      editor={editor}
      tippyOptions={{ duration: 100 }}
      shouldShow={({ editor, view, state, oldState, from, to }) => {
        // Only show when citation mark is active and there's a selection or cursor in citation
        return editor.isActive('citationMark');
      }}
    >
      <div className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 shadow-lg max-w-xs">
        <button
          onClick={handleUrlClick}
          className="text-sm text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 underline cursor-pointer truncate block w-full text-left"
          title={getDisplayUrl()}
        >
          {getDisplayUrl()}
        </button>
      </div>
    </BubbleMenu>
  );
}; 