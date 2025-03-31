/** @type {import('tailwindcss').Config} */

module.exports = {
  darkMode: "class",
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",

    // Or if using `src` directory:
    "./src/**/*.{js,ts,jsx,tsx,mdx}",

    // tremor
    "./node_modules/@tremor/**/*.{js,ts,jsx,tsx}",
  ],

  theme: {
    transparent: "transparent",
    current: "currentColor",
    extend: {
      transitionProperty: {
        spacing: "margin, padding",
      },
      keyframes: {
        "subtle-pulse": {
          "0%, 100%": { opacity: 0.9 },
          "50%": { opacity: 0.5 },
        },
        pulse: {
          "0%, 100%": { opacity: 0.9 },
          "50%": { opacity: 0.4 },
        },
        "fade-in-scale": {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
      },
      animation: {
        "fade-in-up": "fadeInUp 0.5s ease-out",
        "subtle-pulse": "subtle-pulse 2s ease-in-out infinite",
        pulse: "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in-scale": "fade-in-scale 0.3s ease-out",
      },

      gradientColorStops: {
        "neutral-10": "var(--neutral-10) 5%",
      },
      screens: {
        "2xl": "1420px",
        "3xl": "1700px",
        "4xl": "2000px",
        mobile: { max: "767px" },
        desktop: "768px",
        tall: { raw: "(min-height: 800px)" },
        short: { raw: "(max-height: 799px)" },
        "very-short": { raw: "(max-height: 600px)" },
      },
      fontFamily: {
        sans: ["Hanken Grotesk", "var(--font-inter)", "sans-serif"],
        hanken: ["Hanken Grotesk", "sans-serif"],
      },
      width: {
        "message-xs": "450px",
        "message-sm": "550px",
        "message-default": "740px",
        "searchbar-xs": "560px",
        "searchbar-sm": "660px",
        searchbar: "850px",
        "document-sidebar": "800px",
        "document-sidebar-large": "1000px",
        "searchbar-max": "60px",
      },
      maxWidth: {
        "document-sidebar": "1000px",
        "message-max": "850px",
        "content-max": "725px",
        "searchbar-max": "800px",
      },
      colors: {
        // code styling
        "code-bg": "#000",
        "code-text": "var(--code-text)",
        "token-comment": "var(--token-comment)",
        "token-punctuation": "var(--token-punctuation)",
        "token-property": "var(--token-property)",
        "token-selector": "var(--token-selector)",
        "token-atrule": "var(--token-atrule)",
        "token-function": "var(--token-function)",
        "token-regex": "var(--token-regex)",
        "token-attr-name": "var(--token-attr-name)",
        "non-selectable": "var(--non-selectable)",

        "gray-background": "var(--gray-background)",

        "new-background": "var(--new-background)",
        "new-background-light": "var(--new-background-light)",
        warning: "hsl(var(--warning))",
        "warning-foreground": "hsl(var(--warning-foreground))",

        "input-text": "var(--input-text)",

        // background
        background: "var(--background-input-background)",
        "input-border": "var(--input-border)",
        "input-background": "var(--input-background)",
        "input-option": "var(--input-option)",
        "input-option-hover": "var(--input-option-hover)",
        "accent-background": "var(--accent-background)",
        "accent-background-hovered": "var(--accent-background-hovered)",
        "accent-background-selected": "var(--accent-background-selected)",
        "background-50": "var(--background-50)",
        "background-dark": "var(--off-white)",
        "background-100": "var(--neutral-100-border-light)",
        "background-125": "var(--neutral-125)",
        "background-150": "var(--neutral-150)",
        "background-200": "var(--neutral-200-border)",
        "background-300": "var(--neutral-300-border-medium)",
        "background-400": "var(--neutral-400-border-strong)",
        "background-500": "var(--neutral-500)",
        "background-600": "var(--neutral-600-border-dark)",
        "background-700": "var(--neutral-700)",
        "background-800": "var(--neutral-800)",
        "background-900": "var(--neutral-900)",

        "gray-background": "var(--neutral-100-border-light)",
        "gray-background-dark": "var(--neutral-200-border)",
        "gray-background-100": "var(--neutral-100-border-light)",
        "gray-background-125": "var(--neutral-125)",
        "gray-background-150": "var(--neutral-150)",
        "gray-background-200": "var(--neutral-200-border)",
        "gray-background-300": "var(--neutral-300-border-medium)",
        "gray-background-400": "var(--neutral-400-border-strong)",
        "gray-background-500": "var(--neutral-500)",
        "gray-background-600": "var(--neutral-600-border-dark)",
        "gray-background-700": "var(--neutral-700)",
        "gray-background-800": "var(--neutral-800)",
        "gray-background-900": "var(--neutral-900)",

        "text-history-sidebar-button": "var(--text-800)",

        "background-inverted": "var(--background-inverted)",
        "background-emphasis": "var(--background-emphasis)",
        "background-strong": "var(--background-strong)",
        "background-search": "var(--white-card-popover)",

        "background-history-sidebar-button-hover": "var(--neutral-200-border)",
        "divider-history-sidebar-bar": "var(--neutral-200-border)",
        "text-mobile-sidebar": "var(--text-800)",
        "background-search-filter": "var(--neutral-100-border-light)",
        "background-search-filter-dropdown": "var(--neutral-100-border-light)",

        "user-bubble": "var(--off-white)",

        // colors for sidebar in chat, search, and manage settings

        "background-chatbar": "var(--background-chatbar-sidebar)",
        "text-sidebar": "var(--text-500)",

        "toggled-background": "var(--neutral-400-border-strong)",
        "untoggled-background": "var(--neutral-200-border)",
        "background-starter-message": "var(--background-input-background)",
        "background-starter-message-hover": "var(--neutral-100-border-light)",

        "text-sidebar-toggled-header": "var(--text-800)",
        "text-sidebar-header": "var(--text-800)",

        "background-back-button": "var(--neutral-200-border)",
        "text-back-button": "var(--neutral-800)",

        // Settings
        "text-sidebar-subtle": "var(--neutral-500)",
        "icon-settings-sidebar": "var(--neutral-600-border-dark)",
        "text-settings-sidebar": "var(--neutral-600-border-dark)",
        "text-settings-sidebar-strong": "var(--neutral-900)",
        "background-settings-hover": "var(--neutral-200-border)",

        "text-application-toggled": "var(--text-800)",
        "text-application-untoggled": "var(--text-500)",
        "text-application-untoggled-hover": "var(--text-700)",

        "background-chat-hover": "var(--background-chat-hover-selected)",
        "background-chat-selected": "var(--background-chat-hover-selected)",
        black: "var(--black)",
        white: "var(--white-card-popover)",

        // Background for chat messages (user bubbles)
        user: "var(--off-white)",

        "userdropdown-background": "var(--neutral-800)",
        "text-mobile-sidebar-toggled": "var(--neutral-800)",
        "text-mobile-sidebar-untoggled": "var(--neutral-500)",
        "text-editing-message": "var(--neutral-800)",
        "background-sidebar": "var(--background-chatbar-sidebar)",
        "background-search-filter": "var(--neutral-100-border-light)",
        "background-search-filter-dropdown": "var(--background-hover)",

        "background-toggle": "var(--neutral-100-border-light)",

        // Colors for the search toggle buttons
        "background-agentic-toggled": "var(--light-success)",
        "background-agentic-untoggled": "var(--undo)",
        "text-agentic-toggled": "var(--neutral-800)",
        "text-agentic-untoggled": "var(--white-card-popover)",
        "text-chatbar-subtle": "var(--text-chatbar-subtle)",
        "text-chatbar": "var(--neutral-800)",

        // Color for the star indicator on high quality search results.
        "star-indicator": "var(--neutral-100-border-light)",

        // Backgrounds for submit buttons on search and chat
        "submit-background": "var(--neutral-800)",
        "disabled-submit-background": "var(--neutral-400-border-strong)",

        input: "var(--white-card-popover)",

        text: "var(--neutral-950)",
        "text-darker": "var(--text-darker)",
        "text-dark": "var(--text-dark)",
        "sidebar-border": "var(--neutral-200-border)",
        "text-gray": "var(--text-gray)",

        "text-light": "var(--text-light)",

        "text-50": "var(--neutral-50)",
        "text-100": "var(--neutral-100-border-light)",
        "text-200": "var(--neutral-200-border)",
        "text-300": "var(--neutral-300-border-medium)",
        "text-400": "var(--neutral-400-border-strong)",
        "text-500": "var(--neutral-500)",
        "text-600": "var(--neutral-600-border-dark)",
        "text-700": "var(--neutral-700)",
        "text-800": "var(--neutral-800)",
        "text-900": "var(--neutral-900)",
        "text-950": "var(--neutral-950)",
        "text-muted": "var(--p)",

        "user-text": "var(--text-800)",

        description: "var(--text-400)",
        subtle: "var(--neutral-600-border-dark)",
        default: "var(--text-600)",
        emphasis: "var(--text-700)",
        strong: "var(--text-900)",

        // borders
        border: "var(--neutral-200-border)",
        "border-light": "var(--neutral-100-border-light)",
        "border-medium": "var(--neutral-300-border-medium)",
        "border-strong": "var(--neutral-400-border-strong)",
        "border-dark": "var(--neutral-600-border-dark)",
        "non-selectable-border": "var(--non-selectable-border)",

        inverted: "var(--white-card-popover)",
        link: "var(--link)",
        "link-hover": "var(--link-hover)",

        // one offs
        error: "var(--error)",
        success: "var(--success)",
        alert: "var(--alert)",
        accent: "var(--accent)",
        "agent-sidebar": "var(--agent-sidebar)",
        agent: "var(--agent)",
        "lighter-agent": "var(--lighter-agent)",
        "agent-hovered": "var(--agent-hovered)",
        // hover
        "hover-light": "var(--hover-light)",
        "hover-lightish": "var(--neutral-125)",

        hover: "var(--hover)",
        "hover-emphasis": "var(--neutral-300-border-medium)",
        "accent-hover": "var(--accent-hover)",

        // keyword highlighting
        highlight: {
          text: "var(--highlight-text)",
        },

        // scrollbar
        scrollbar: {
          track: "var(--scrollbar-track)",
          thumb: "var(--scrollbar-thumb)",
          "thumb-hover": "var(--scrollbar-thumb-hover)",

          dark: {
            thumb: "var(--scrollbar-dark-thumb)",
            "thumb-hover": "var(--scrollbar-dark-thumb-hover)",
          },
        },

        // for display documents
        document: "var(--document-color)",

        // light mode
        tremor: {
          brand: {
            faint: "var(--tremor-brand-faint)",
            muted: "var(--tremor-brand-muted)",
            subtle: "var(--tremor-brand-subtle)",
            DEFAULT: "var(--tremor-brand-default)",
            emphasis: "var(--tremor-brand-emphasis)",
            inverted: "var(--tremor-brand-inverted)",
          },
          background: {
            muted: "var(--tremor-background-muted)",
            subtle: "var(--tremor-background-subtle)",
            DEFAULT: "var(--tremor-background-default)",
            emphasis: "var(--tremor-background-emphasis)",
          },
          border: {
            DEFAULT: "var(--tremor-border-default)",
          },
          ring: {
            DEFAULT: "var(--tremor-ring-default)",
          },
          content: {
            subtle: "var(--tremor-content-subtle)",
            DEFAULT: "var(--tremor-content-default)",
            emphasis: "var(--tremor-content-emphasis)",
            strong: "var(--tremor-content-strong)",
            inverted: "var(--tremor-content-inverted)",
          },
        },
        // dark mode
        "dark-tremor": {
          brand: {
            faint: "var(--dark-tremor-brand-faint)",
            muted: "var(--dark-tremor-brand-muted)",
            subtle: "var(--dark-tremor-brand-subtle)",
            DEFAULT: "var(--dark-tremor-brand-default)",
            emphasis: "var(--dark-tremor-brand-emphasis)",
            inverted: "var(--dark-tremor-brand-inverted)",
          },
          background: {
            muted: "var(--dark-tremor-background-muted)",
            subtle: "var(--dark-tremor-background-subtle)",
            DEFAULT: "var(--dark-tremor-background-default)",
            emphasis: "var(--dark-tremor-background-emphasis)",
          },
          border: {
            DEFAULT: "var(--dark-tremor-border-default)",
          },
          ring: {
            DEFAULT: "var(--dark-tremor-ring-default)",
          },
          content: {
            subtle: "var(--dark-tremor-content-subtle)",
            DEFAULT: "var(--dark-tremor-content-default)",
            emphasis: "var(--dark-tremor-content-emphasis)",
            strong: "var(--dark-tremor-content-strong)",
            inverted: "var(--dark-tremor-content-inverted)",
          },
        },
        foreground: "var(--foreground)",
      },
      boxShadow: {
        // light
        "tremor-input": "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        "tremor-card":
          "0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)",
        "tremor-dropdown":
          "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
        // dark
        "dark-tremor-input": "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        "dark-tremor-card":
          "0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)",
        "dark-tremor-dropdown":
          "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
      },
      borderRadius: {
        "tremor-small": "0.375rem",
        "tremor-default": "0.5rem",
        "tremor-full": "9999px",
      },
      fontSize: {
        "2xs": "0.625rem",
        "code-sm": "small",
        "tremor-label": ["0.75rem"],
        "tremor-default": ["0.875rem", { lineHeight: "1.25rem" }],
        "tremor-title": ["1.125rem", { lineHeight: "1.75rem" }],
        "tremor-metric": ["1.875rem", { lineHeight: "2.25rem" }],
      },
      fontWeight: {
        description: "375",
        "token-bold": "bold",
      },
      fontStyle: {
        "token-italic": "italic",
      },
      calendar: {
        // Light mode
        "bg-selected": "var(--calendar-bg-selected)",
        "bg-outside-selected": "var(--calendar-bg-outside-selected)",
        "text-muted": "var(--calendar-text-muted)",
        "text-selected": "var(--calendar-text-selected)",
        "range-start": "var(--calendar-range-start)",
        "range-middle": "var(--calendar-range-middle)",
        "range-end": "var(--calendar-range-end)",
        "text-in-range": "var(--calendar-text-in-range)",

        // Dark mode
        "bg-selected-dark": "var(--calendar-bg-selected-dark)",
        "bg-outside-selected-dark": "var(--calendar-bg-outside-selected-dark)",
        "text-muted-dark": "var(--calendar-text-muted-dark)",
        "text-selected-dark": "var(--calendar-text-selected-dark)",
        "range-start-dark": "var(--calendar-range-start-dark)",
        "range-middle-dark": "var(--calendar-range-middle-dark)",
        "range-end-dark": "var(--calendar-range-end-dark)",
        "text-in-range-dark": "var(--calendar-text-in-range-dark)",

        // Hover effects
        "hover-bg": "var(--calendar-hover-bg)",
        "hover-bg-dark": "var(--calendar-hover-bg-dark)",
        "hover-text": "var(--calendar-hover-text)",
        "hover-text-dark": "var(--calendar-hover-text-dark)",

        // Today's date
        "today-bg": "var(--calendar-today-bg)",
        "today-bg-dark": "var(--calendar-today-bg-dark)",
        "today-text": "var(--calendar-today-text)",
        "today-text-dark": "var(--calendar-today-text-dark)",
      },
    },
  },
  safelist: [
    {
      pattern:
        /^(bg-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-(?:50|100|200|300|400|500|600|700|800|900|950))$/,
      variants: ["hover", "ui-selected"],
    },
    {
      pattern:
        /^(text-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-(?:50|100|200|300|400|500|600|700|800|900|950))$/,
      variants: ["hover", "ui-selected"],
    },
    {
      pattern:
        /^(border-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-(?:50|100|200|300|400|500|600|700|800|900|950))$/,
      variants: ["hover", "ui-selected"],
    },
    {
      pattern:
        /^(ring-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-(?:50|100|200|300|400|500|600|700|800|900|950))$/,
    },
    {
      pattern:
        /^(stroke-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-(?:50|100|200|300|400|500|600|700|800|900|950))$/,
    },
    {
      pattern:
        /^(fill-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-(?:50|100|200|300|400|500|600|700|800|900|950))$/,
    },
  ],
  plugins: [
    require("@tailwindcss/typography"),
    require("@headlessui/tailwindcss"),
  ],
};
