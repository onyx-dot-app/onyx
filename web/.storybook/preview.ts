import type { Preview } from "@storybook/react";
import { withThemeByClassName } from "@storybook/addon-themes";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import React from "react";
import "../src/app/globals.css";

const preview: Preview = {
  parameters: {
    layout: "centered",
    backgrounds: { disable: true },
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
  ],
};

export default preview;
