import { Mark, mergeAttributes } from '@tiptap/core';

export interface HighlightWithLinkOptions {
  HTMLAttributes: Record<string, any>;
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    highlightWithLink: {
      setHighlightWithLink: (url?: string) => ReturnType;
      toggleHighlightWithLink: (url?: string) => ReturnType;
      unsetHighlightWithLink: () => ReturnType;
    };
  }
}

export const HighlightWithLink = Mark.create<HighlightWithLinkOptions>({
  name: 'highlightWithLink',

  addOptions() {
    return {
      HTMLAttributes: {},
    };
  },

  addAttributes() {
    return {
      url: {
        default: null,
        parseHTML: element => element.getAttribute('data-url'),
        renderHTML: attributes => {
          if (!attributes.url) {
            return {};
          }
          return {
            'data-url': attributes.url,
          };
        },
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'mark[data-url]',
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    return ['mark', mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
      class: 'bg-yellow-200 cursor-pointer hover:bg-yellow-300 transition-colors',
      onClick: `window.open('${HTMLAttributes['data-url']}', '_blank')`,
    }), 0];
  },

  addCommands() {
    return {
      setHighlightWithLink: (url) => ({ commands }) => {
        return commands.setMark(this.name, { url });
      },
      toggleHighlightWithLink: (url) => ({ commands }) => {
        return commands.toggleMark(this.name, { url });
      },
      unsetHighlightWithLink: () => ({ commands }) => {
        return commands.unsetMark(this.name);
      },
    };
  },
});
