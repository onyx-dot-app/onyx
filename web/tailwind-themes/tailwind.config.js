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
        "fade-out-scale": {
          "0%": { opacity: "1", transform: "scale(1)" },
          "100%": { opacity: "0", transform: "scale(0.95)" },
        },
      },
      animation: {
        "fade-in-up": "fadeInUp 0.5s ease-out",
        "subtle-pulse": "subtle-pulse 2s ease-in-out infinite",
        pulse: "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in-scale": "fade-in-scale 0.2s ease-out forwards",
        "fade-out-scale": "fade-out-scale 0.2s ease-in forwards",
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
        // New and updated Figma stylings
        "text-05": "var(--text-05)",
        "text-04": "var(--text-04)",
        "text-03": "var(--text-03)",
        "text-02": "var(--text-02)",
        "text-01": "var(--text-01)",
        "text-inverted-01": "var(--text-inverted-01)",
        "text-inverted-02": "var(--text-inverted-02)",
        "text-inverted-03": "var(--text-inverted-03)",
        "text-inverted-04": "var(--text-inverted-04)",
        "text-inverted-05": "var(--text-inverted-05)",
        "text-light-03": "var(--text-light-03)",
        "text-light-05": "var(--text-light-05)",
        "text-dark-03": "var(--text-dark-03)",
        "text-dark-05": "var(--text-dark-05)",
        "background-neutral-00": "var(--background-neutral-00)",
        "background-neutral-01": "var(--background-neutral-01)",
        "background-neutral-02": "var(--background-neutral-02)",
        "background-neutral-03": "var(--background-neutral-03)",
        "background-neutral-04": "var(--background-neutral-04)",
        "background-neutral-inverted-04":
          "var(--background-neutral-inverted-04)",
        "background-neutral-inverted-03":
          "var(--background-neutral-inverted-03)",
        "background-neutral-inverted-02":
          "var(--background-neutral-inverted-02)",
        "background-neutral-inverted-01":
          "var(--background-neutral-inverted-01)",
        "background-neutral-inverted-00":
          "var(--background-neutral-inverted-00)",
        "background-tint-00": "var(--background-tint-00)",
        "background-tint-01": "var(--background-tint-01)",
        "background-tint-02": "var(--background-tint-02)",
        "background-tint-03": "var(--background-tint-03)",
        "background-tint-04": "var(--background-tint-04)",
        "background-tint-inverted-04": "var(--background-tint-inverted-04)",
        "background-tint-inverted-03": "var(--background-tint-inverted-03)",
        "background-tint-inverted-02": "var(--background-tint-inverted-02)",
        "background-tint-inverted-01": "var(--background-tint-inverted-01)",
        "background-tint-inverted-00": "var(--background-tint-inverted-00)",
        "border-01": "var(--border-01)",
        "border-02": "var(--border-02)",
        "border-03": "var(--border-03)",
        "border-04": "var(--border-04)",
        "border-05": "var(--border-05)",
        "border-inverted-05": "var(--border-inverted-05)",
        "border-inverted-04": "var(--border-inverted-04)",
        "border-inverted-03": "var(--border-inverted-03)",
        "border-inverted-02": "var(--border-inverted-02)",
        "border-inverted-01": "var(--border-inverted-01)",
        "action-link-06": "var(--action-link-06)",
        "action-link-05": "var(--action-link-05)",
        "action-link-04": "var(--action-link-04)",
        "action-link-03": "var(--action-link-03)",
        "action-link-02": "var(--action-link-02)",
        "action-link-01": "var(--action-link-01)",
        "action-danger-06": "var(--action-danger-06)",
        "action-danger-05": "var(--action-danger-05)",
        "action-danger-04": "var(--action-danger-04)",
        "action-danger-03": "var(--action-danger-03)",
        "action-danger-02": "var(--action-danger-02)",
        "action-danger-01": "var(--action-danger-01)",
        "action-text-link-05": "var(--action-text-link-05)",
        "action-text-danger-05": "var(--action-text-danger-05)",
        "highlight-match": "var(--highlight-match)",
        "highlight-selection": "var(--highlight-selection)",
        "highlight-active": "var(--highlight-active)",
        "theme-primary-06": "var(--theme-primary-06)",
        "theme-primary-05": "var(--theme-primary-05)",
        "theme-primary-04": "var(--theme-primary-04)",
        "onyx-ink-100": "var(--onyx-ink-100)",
        "onyx-ink-95": "var(--onyx-ink-95)",
        "onyx-ink-90": "var(--onyx-ink-90)",
        "onyx-chrome-20": "var(--onyx-chrome-20)",
        "onyx-chrome-10": "var(--onyx-chrome-10)",
        "onyx-chrome-00": "var(--onyx-chrome-00)",
        "tint-98": "var(--tint-98)",
        "tint-95": "var(--tint-95)",
        "tint-90": "var(--tint-90)",
        "tint-85": "var(--tint-85)",
        "tint-80": "var(--tint-80)",
        "tint-60": "var(--tint-60)",
        "tint-50": "var(--tint-50)",
        "tint-40": "var(--tint-40)",
        "tint-20": "var(--tint-20)",
        "tint-10": "var(--tint-10)",
        "tint-05": "var(--tint-05)",
        "tint-02": "var(--tint-02)",
        "shadow-01": "var(--shadow-01)",
        "shadow-02": "var(--shadow-02)",
        "shadow-03": "var(--shadow-03)",
        "mask-01": "var(--mask-01)",
        "mask-02": "var(--mask-02)",
        "mask-03": "var(--mask-03)",
        "status-info-05": "var(--status-info-05)",
        "status-info-02": "var(--status-info-02)",
        "status-info-01": "var(--status-info-01)",
        "status-info-00": "var(--status-info-00)",
        "status-success-05": "var(--status-success-05)",
        "status-success-02": "var(--status-success-02)",
        "status-success-01": "var(--status-success-01)",
        "status-success-00": "var(--status-success-00)",
        "status-warning-05": "var(--status-warning-05)",
        "status-warning-02": "var(--status-warning-02)",
        "status-warning-01": "var(--status-warning-01)",
        "status-warning-00": "var(--status-warning-00)",
        "status-error-05": "var(--status-error-05)",
        "status-error-02": "var(--status-error-02)",
        "status-error-01": "var(--status-error-01)",
        "status-error-00": "var(--status-error-00)",
        "status-text-success-05": "var(--status-text-success-05)",
        "status-text-info-05": "var(--status-text-info-05)",
        "status-text-warning-05": "var(--status-text-warning-05)",
        "status-text-error-05": "var(--status-text-error-05)",

        "code-code": "var(--code-code)",
        "code-comment": "var(--code-comment)",
        "code-keyword": "var(--code-keyword)",
        "code-string": "var(--code-string)",
        "code-number": "var(--code-number)",
        "code-definition": "var(--code-definition)",

        // Tailwind defaults
        background: "var(--background-tint-01)",
        foreground: "var(--background-tint-inverted-01)",
        border: "var(--border-01)",
        text: "var(--text-04)",

        // (OLD) code styling
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
      },
      boxShadow: {
        "01": "0px 2px 8px 0px var(--shadow-01)",
        "02": "0px 2px 8px 0px var(--shadow-02)",
        "03": "0px 2px 8px 0px var(--shadow-03)",

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
        "02": "var(--border-radius-02)",
        "04": "var(--border-radius-04)",
        "08": "var(--border-radius-08)",
        12: "var(--border-radius-12)",
        16: "var(--border-radius-16)",
        full: "var(--border-radius-full)",
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
      spacing: {
        "spacing-inline-mini": "var(--spacing-inline-mini)",
        "spacing-inline": "var(--spacing-inline)",
        "spacing-interline-mini": "var(--spacing-interline-mini)",
        "spacing-interline": "var(--spacing-interline)",
        "spacing-paragraph": "var(--spacing-paragraph)",
        "spacing-headline": "var(--spacing-headline)",
        "spacing-headline-large": "var(--spacing-headline-large)",
        "spacing-block": "var(--spacing-block)",
        "spacing-section": "var(--spacing-section)",
        "padding-button": "var(--padding-button)",
        "padding-content": "var(--padding-content)",
        "padding-block-end": "var(--padding-block-end)",
        "padding-body-main": "var(--padding-body-main)",
        "padding-section": "var(--padding-section)",
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
    require("tailwindcss-animate"),
  ],
};
