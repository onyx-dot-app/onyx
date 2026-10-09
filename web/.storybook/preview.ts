import type { Preview } from "@storybook/react-vite";
import { withThemeByClassName } from "@storybook/addon-themes";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { NextIntlClientProvider } from "next-intl";
import React from "react";
import "../src/app/globals.css";

import englishMessages from "../src/i18n/messages/en.json";

const preview: Preview = {
  parameters: {
    layout: "centered",
    backgrounds: { disabled: true },
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
  },
  decorators: [
    withThemeByClassName({
      themes: {
        light: "",
        dark: "dark",
      },
      defaultTheme: "light",
    }),
    (Story) =>
      React.createElement(
        TooltipPrimitive.Provider,
        null,
        React.createElement(Story)
      ),
    // Stories always render the English catalog, matching the app default.
    (Story) =>
      React.createElement(
        NextIntlClientProvider,
        { locale: "en", messages: englishMessages },
        React.createElement(Story)
      ),
  ],
};

export default preview;
