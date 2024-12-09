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
      },
      animation: {
        "fade-in-up": "fadeInUp 0.5s ease-out",
        "subtle-pulse": "subtle-pulse 2s ease-in-out infinite",
        pulse: "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },

      gradientColorStops: {
        "neutral-10": "#e5e5e5 5%",
      },
      screens: {
        "2xl": "1420px",
        "3xl": "1700px",
        "4xl": "2000px",
        mobile: { max: "767px" },
        desktop: "768px",
      },
      fontFamily: {
        sans: ["var(--font-inter)"],
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
        "code-bg": "var(--black)",
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

        // background
        background: "var(--background)",
        "background-100": "var(--background-100)",
        "background-125": "var(--background-125)",
        "background-150": "var(--background-150)",
        "background-200": "var(--background-200)",
        "background-300": "var(--background-300)",
        "background-400": "var(--background-400)",
        "background-500": "var(--background-500)",
        "background-600": "var(--background-600)",
        "background-700": "var(--background-700)",
        "background-800": "var(--background-800)",
        "background-900": "var(--background-900)",

        "background-inverted": "var(--background-inverted)",
        "background-emphasis": "var(--background-emphasis)",
        "background-strong": "var(--background-strong)",
        "background-search": "var(--white)",

        "background-history-sidebar-button-hover": "var(--background-200)",
        "text-history-sidebar-button": "var(--text-800)",
        "divider-history-sidebar-bar": "var(--border)",
        "text-mobile-sidebar": "var(--text-800)",
        "background-search-filter": "var(--background-100)",
        "background-search-filter-dropdown": "var(--background-100)",

        // colors for sidebar in chat, search, and manage settings
        "background-sidebar": "var(--background-100)",
        "background-chatbar": "var(--background-100)",
        "text-sidebar": "var(--text-500)",

        "toggled-background": "var(--background-400)",
        "untoggled-background": "var(--background-200)",
        "background-starter-message": "var(--background)",
        "background-starter-message-hover": "var(--background-100)",

        "text-sidebar-toggled-header": "var(--text-800)",
        "text-sidebar-header": "var(--text-800)",

        "background-back-button": "var(--background-200)",
        "text-back-button": "var(--text-800)",

        // Settings
        "text-sidebar-subtle": "var(--text-500)",
        "icon-settings-sidebar": "var(--text-600)",
        "text-settings-sidebar": "var(--text-600)",
        "text-settings-sidebar-strong": "var(--text-900)",
        "background-settings-hover": "var(--background-200)",

        "text-application-toggled": "var(--text-800)",
        "text-application-untoggled": "var(--text-500)",
        "text-application-untoggled-hover": "var(--text-700)",

        "background-chat-hover": "var(--background-200)",
        "background-chat-selected": "var(--background-200)",

        // Background for chat messages (user bubbles)
        user: "var(--user-bubble)",

        "background-toggle": "var(--background-100)",

        // Colors for the search toggle buttons
        "background-agentic-toggled": "var(--light-success)",
        "background-agentic-untoggled": "var(--undo)",
        "text-agentic-toggled": "var(--text-800)",
        "text-agentic-untoggled": "var(--white)",
        "text-chatbar-subtle": "var(--text-500)",
        "text-chatbar": "var(--text-800)",

        // Color for the star indicator on high quality search results.
        "star-indicator": "var(--background-100)",

        // Backgrounds for submit buttons on search and chat
        "submit-background": "var(--background-800)",
        "disabled-submit-background": "var(--background-400)",

        input: "var(--white)",

        "text-50": "var(--text-50)",
        "text-100": "var(--text-100)",
        "text-200": "var(--text-200)",
        "text-300": "var(--text-300)",
        "text-400": "var(--text-400)",
        "text-500": "var(--text-500)",
        "text-600": "var(--text-600)",
        "text-700": "var(--text-700)",
        "text-800": "var(--text-800)",
        "text-900": "var(--text-900)",
        "text-950": "var(--text-950)",
        // Light mode
        // Light mode
        "calendar-bg-selected": "var(--background-800)",
        "calendar-bg-outside-selected": "var(--background-200)",
        "calendar-text-muted": "var(--text-400)",
        "calendar-text-selected": "var(--white)",
        "calendar-range-middle": "var(--neutral-800)",
        "calendar-range-end": "var(--white)",
        "calendar-text-in-range": "var(--text-200)",
        "calendar-text-end": "var(--text-900)",

        // Dark mode
        "calendar-bg-outside-selected-dark": "var(--background-700)",
        "calendar-text-muted-dark": "var(--text-500)",
        "calendar-text-selected-dark": "var(--white)",
        "calendar-range-middle-dark": "var(--background-800)",
        "calendar-text-in-range-dark": "var(--text-200)",

        // Hover effects
        "calendar-hover-bg": "var(--background-200)",
        "calendar-hover-bg-dark": "var(--background-700)",
        "calendar-hover-text": "var(--text-800)",
        "calendar-hover-text-dark": "var(--text-200)",

        // Today's date
        "calendar-today-bg": "var(--background-100)",
        "calendar-today-bg-dark": "var(--background-800)",
        "calendar-today-text": "var(--text-800)",
        "calendar-today-text-dark": "var(--text-200)",

        "user-text": "var(--text-800)",

        description: "var(--text-400)",
        subtle: "var(--text-500)",
        default: "var(--text-600)",
        emphasis: "var(--text-700)",
        strong: "var(--text-900)",

        // borders
        border: "var(--border)",
        "border-light": "var(--border-light)",
        "border-medium": "var(--border-medium)",
        "border-strong": "var(--border-strong)",
        "border-dark": "var(--border-dark)",
        "non-selectable-border": "#f5c2c7",

        inverted: "var(--white)",
        link: "var(--link)",
        "link-hover": "var(--link-hover)",

        // one offs
        error: "var(--error)",
        success: "var(--success)",
        alert: "var(--alert)",
        accent: "var(--accent)",

        // hover
        "hover-light": "var(--background-100)",
        "hover-lightish": "var(--background-125)",

        hover: "var(--background-200)",
        "hover-emphasis": "var(--background-300)",
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
            DEFAULT: "#3b82f6", // blue-500
            emphasis: "var(--tremor-brand-emphasis)",
            inverted: "var(--tremor-brand-inverted)",
          },
          background: {
            muted: "var(--tremor-background-muted)",
            subtle: "var(--tremor-background-subtle)",
            DEFAULT: "#ffffff", // white
            emphasis: "var(--tremor-background-emphasis)",
          },
          border: {
            DEFAULT: "#e5e7eb", // gray-200
          },
          ring: {
            DEFAULT: "#e5e7eb", // gray-200
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
            DEFAULT: "#3b82f6", // blue-500
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
            DEFAULT: "#1f2937", // gray-800
          },
          ring: {
            DEFAULT: "#1f2937", // gray-800
          },
          content: {
            subtle: "var(--dark-tremor-content-subtle)",
            DEFAULT: "var(--dark-tremor-content-default)",
            emphasis: "var(--dark-tremor-content-emphasis)",
            strong: "var(--dark-tremor-content-strong)",
            inverted: "var(--dark-tremor-content-inverted)",
          },
        },
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
