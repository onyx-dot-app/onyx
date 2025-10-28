import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const fonts = {
  // Heading
  headingH1: "font-heading-h1",
  headingH2: "font-heading-h2",
  headingH3: "font-heading-h3",
  headingH3Muted: "font-heading-h3-muted",

  // Main Content
  mainContentBody: "font-main-content-body",
  mainContentMuted: "font-main-content-muted",
  mainContentEmphasis: "font-main-content-emphasis",
  mainContentMono: "font-main-content-mono",

  // Main UI
  mainUiBody: "font-main-ui-body",
  mainUiMuted: "font-main-ui-muted",
  mainUiAction: "font-main-ui-action",
  mainUiMono: "font-main-ui-mono",

  // Secondary
  secondaryBody: "font-secondary-body",
  secondaryAction: "font-secondary-action",
  secondaryMono: "font-secondary-mono",

  // Figure
  figureSmallLabel: "font-figure-small-label",
  figureSmallValue: "font-figure-small-value",
  figureKeystroke: "font-figure-keystroke",
};

const colors = {
  text05: "text-text-05",
  text04: "text-text-04",
  text03: "text-text-03",
  text02: "text-text-02",
  text01: "text-text-01",

  inverted: {
    text05: "text-text-inverted-05",
    text04: "text-text-inverted-04",
    text03: "text-text-inverted-03",
    text02: "text-text-inverted-02",
    text01: "text-text-inverted-01",
  },
};

export interface TextProps extends HTMLAttributes<HTMLParagraphElement> {
  nowrap?: boolean;

  // Fonts
  headingH1?: boolean;
  headingH2?: boolean;
  headingH3?: boolean;
  headingH3Muted?: boolean;
  mainContentBody?: boolean;
  mainContentMuted?: boolean;
  mainContentEmphasis?: boolean;
  mainContentMono?: boolean;
  mainUiBody?: boolean;
  mainUiMuted?: boolean;
  mainUiAction?: boolean;
  mainUiMono?: boolean;
  secondaryBody?: boolean;
  secondaryAction?: boolean;
  secondaryMono?: boolean;
  figureSmallLabel?: boolean;
  figureSmallValue?: boolean;
  figureKeystroke?: boolean;

  // Colors
  text05?: boolean;
  text04?: boolean;
  text03?: boolean;
  text02?: boolean;
  text01?: boolean;
  inverted?: boolean;
}

export default function Text({
  nowrap,
  headingH1,
  headingH2,
  headingH3,
  headingH3Muted,
  mainContentBody,
  mainContentMuted,
  mainContentEmphasis,
  mainContentMono,
  mainUiBody,
  mainUiMuted,
  mainUiAction,
  mainUiMono,
  secondaryBody,
  secondaryAction,
  secondaryMono,
  figureSmallLabel,
  figureSmallValue,
  figureKeystroke,
  text05,
  text04,
  text03,
  text02,
  text01,
  inverted,
  children,
  className,
  ...rest
}: TextProps) {
  const font = headingH1
    ? "headingH1"
    : headingH2
      ? "headingH2"
      : headingH3
        ? "headingH3"
        : headingH3Muted
          ? "headingH3Muted"
          : mainContentBody
            ? "mainContentBody"
            : mainContentMuted
              ? "mainContentMuted"
              : mainContentEmphasis
                ? "mainContentEmphasis"
                : mainContentMono
                  ? "mainContentMono"
                  : mainUiBody
                    ? "mainUiBody"
                    : mainUiMuted
                      ? "mainUiMuted"
                      : mainUiAction
                        ? "mainUiAction"
                        : mainUiMono
                          ? "mainUiMono"
                          : secondaryBody
                            ? "secondaryBody"
                            : secondaryAction
                              ? "secondaryAction"
                              : secondaryMono
                                ? "secondaryMono"
                                : figureSmallLabel
                                  ? "figureSmallLabel"
                                  : figureSmallValue
                                    ? "figureSmallValue"
                                    : figureKeystroke
                                      ? "figureKeystroke"
                                      : "mainUiBody";

  const color = text01
    ? "text01"
    : text02
      ? "text02"
      : text03
        ? "text03"
        : text04
          ? "text04"
          : text05
            ? "text05"
            : "text05";

  return (
    <p
      {...rest}
      className={cn(
        fonts[font],
        inverted ? colors.inverted[color] : colors[color],
        nowrap && "whitespace-nowrap",
        className
      )}
    >
      {children}
    </p>
  );
}
