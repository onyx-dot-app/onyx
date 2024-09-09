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
        "code-bg": "black", // black
        "code-text": "#e0e0e0", // light gray
        "token-comment": "#608b4e", // green
        "token-punctuation": "#d4d4d4", // light gray
        "token-property": "#569cd6", // blue
        "token-selector": "#e07b53", // more vibrant orange
        "token-atrule": "#d18ad8", // more vibrant purple
        "token-function": "#f0e68c", // more vibrant light yellow
        "token-regex": "#9cdcfe", // light blue
        "token-attr-name": "#9cdcfe", // light blue

        "non-selectable": "#f8d7da", // red-100

        // background
        "background-search": "#ffffff", // white

        input: "#ffffff",

        background: "#fafafa", // 50
        "background-100": "#f5f5f5", // neutral-100
        "background-125": "#F1F2F4", // gray-125
        "background-150": "#EAEAEA", // gray-150
        "background-200": "#e5e5e5", // neutral-200
        "background-300": "#d4d4d4", // neutral-300
        "background-400": "#a3a3a3", // neutral-400
        "background-600": "#525252", // neutral-800
        "background-500": "#737373", // neutral-400
        "background-600": "#525252", // neutral-400
        "background-700": "#404040", // neutral-400
        "background-800": "#262626", // neutral-800
        "background-900": "#111827", // gray-900
        "background-inverted": "#000000", // black

        "background-emphasis": "#f6f7f8",
        "background-strong": "#eaecef",

        // text or icons
        "text-50": "#fafafa", // 50, neutral-50
        "text-100": "#f5f5f5", // lighter, neutral-100
        "text-200": "#e5e5e5", // light, neutral-200
        "text-300": "#d4d4d4", // stronger, neutral-300
        "text-400": "#a3a3a3", // medium, neutral-400
        "text-500": "#737373", // darkMedium, neutral-500
        "text-600": "#525252", // dark, neutral-600
        "text-700": "#404040", // solid, neutral-700
        "text-800": "#262626", // solidDark, neutral-800
        "text-900": "#111827", // neutral-900
        "text-950": "#0a0a0a", // solidDark, neutral-800

        description: "#a3a3a3",
        subtle: "#6b7280", // gray-500
        default: "#4b5563", // gray-600
        emphasis: "#374151", // gray-700
        strong: "#111827", // gray-900

        link: "#3b82f6", // blue-500
        "link-hover": "#1d4ed8", // blue-700
        inverted: "#ffffff", // white

        // one offs
        error: "#ef4444", // red-500
        success: "#059669", // emerald-600
        alert: "#f59e0b", // amber-600
        accent: "#6366F1", // indigo-500

        // borders
        border: "#d1d5db", // gray-200
        "border-light": "#f3f4f6", // gray-100
        "border-medium": "#d1d5db", // gray-300
        "border-strong": "#9ca3af", // gray-400
        "border-dark": "#525252", // neutral-600
        "non-selectable-border": "#f5c2c7", // red-200

        // hover
        "hover-light": "#f3f4f6", // gray-100
        "hover-lightish": "#EAEBEF", // gray-160

        hover: "#e5e7eb", // gray-200
        "hover-emphasis": "#d1d5db", // gray-300
        "accent-hover": "#4F46E5",

        // keyword highlighting
        highlight: {
          text: "#fef9c3", // yellow-100
        },

        // scrollbar
        scrollbar: {
          track: "#f9fafb",
          thumb: "#e5e7eb",
          "thumb-hover": "#d1d5db",

          dark: {
            thumb: "#989a9c",
            "thumb-hover": "#c7cdd2",
          },
        },

        // bubbles in chat for each "user"
        user: "#F1F2F4", // near gray-100
        ai: "#60a5fa", // blue-400

        // for display documents
        document: "#f43f5e", // pink-500

        // light mode
        tremor: {
          brand: {
            faint: "#eff6ff", // blue-50
            muted: "#bfdbfe", // blue-200
            subtle: "#60a5fa", // blue-400
            DEFAULT: "#3b82f6", // blue-500
            emphasis: "#1d4ed8", // blue-700
            inverted: "#ffffff", // white
          },
          background: {
            muted: "#f9fafb", // gray-50
            subtle: "#f3f4f6", // gray-100
            DEFAULT: "#ffffff", // white
            emphasis: "#374151", // gray-700
          },
          border: {
            DEFAULT: "#e5e7eb", // gray-200
          },
          ring: {
            DEFAULT: "#e5e7eb", // gray-200
          },
          content: {
            subtle: "#9ca3af", // gray-400
            DEFAULT: "#4b5563", // gray-600
            emphasis: "#374151", // gray-700
            strong: "#111827", // gray-900
            inverted: "#ffffff", // white
          },
        },
        // dark mode
        "dark-tremor": {
          brand: {
            faint: "#0B1229", // custom
            muted: "#172554", // blue-950
            subtle: "#1e40af", // blue-800
            DEFAULT: "#3b82f6", // blue-500
            emphasis: "#60a5fa", // blue-400
            inverted: "#030712", // gray-950
          },
          background: {
            muted: "#131A2B", // custom
            subtle: "#1f2937", // gray-800
            DEFAULT: "#111827", // gray-900
            emphasis: "#d1d5db", // gray-300
          },
          border: {
            DEFAULT: "#1f2937", // gray-800
          },
          ring: {
            DEFAULT: "#1f2937", // gray-800
          },
          content: {
            subtle: "#6b7280", // gray-500
            DEFAULT: "#d1d5db", // gray-300
            emphasis: "#f3f4f6", // gray-100
            strong: "#f9fafb", // gray-50
            inverted: "#000000", // black
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
