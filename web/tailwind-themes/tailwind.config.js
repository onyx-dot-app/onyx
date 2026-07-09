const plugin = require("tailwindcss/plugin");

/** @type {import('tailwindcss').Config} */

module.exports = {
  presets: [require("@onyx-ai/opal/tailwind-preset")],
  darkMode: "class",
  content: ["./src/**/*.{js,jsx,ts,tsx}", "./lib/opal/**/*.{js,jsx,ts,tsx}"],
  theme: {
    container: {
      center: true,
    },
    transparent: "transparent",
    current: "currentColor",
    extend: {
      lineClamp: {
        7: "7",
        8: "8",
        9: "9",
        10: "10",
      },
      transitionProperty: {
        spacing: "margin, padding",
      },
      keyframes: {
        "fade-in-up": {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in-up": "fade-in-up 0.5s ease-out",
      },
      gradientColorStops: {
        "neutral-10": "var(--neutral-10) 5%",
      },
      screens: {
        sm: "724px",
        md: "912px",
        lg: "1232px",
        "2xl": "1420px",
        "3xl": "1700px",
        "4xl": "2000px",
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
        // Code syntax highlighting — not part of the Opal design-token palette
        "code-code": "var(--code-code)",
        "code-comment": "var(--code-comment)",
        "code-keyword": "var(--code-keyword)",
        "code-string": "var(--code-string)",
        "code-number": "var(--code-number)",
        "code-definition": "var(--code-definition)",
        "background-code-01": "var(--background-code-01)",
      },
      fontSize: {
        "code-sm": "small",
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
    plugin(({ addVariant }) => {
      addVariant("focus-within-nonactive", "&:focus-within:not(:active)");
    }),
    plugin(({ addUtilities }) => {
      addUtilities({
        ".break-anywhere": {
          "overflow-wrap": "anywhere",
        },
      });
    }),
  ],
};
