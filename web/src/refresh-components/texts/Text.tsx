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
  textLight03: "text-text-light-03",
  textLight05: "text-text-light-05",
  textDark03: "text-text-dark-03",
  textDark05: "text-text-dark-05",

  inverted: {
    text05: "text-text-inverted-05",
    text04: "text-text-inverted-04",
    text03: "text-text-inverted-03",
    text02: "text-text-inverted-02",
    text01: "text-text-inverted-01",
    textLight03: "text-text-light-03",
    textLight05: "text-text-light-05",
    textDark03: "text-text-dark-03",
    textDark05: "text-text-dark-05",
  },
};

export interface TextProps extends Omit<HTMLAttributes<HTMLElement>, "as"> {
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
  textLight03?: boolean;
  textLight05?: boolean;
  textDark03?: boolean;
  textDark05?: boolean;

  // Tag type override
  as?: "p" | "span" | "li";
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
  textLight03,
  textLight05,
  textDark03,
  textDark05,
  children,
  className,
  as,
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
            : textLight03
              ? "textLight03"
              : textLight05
                ? "textLight05"
                : textDark03
                  ? "textDark03"
                  : textDark05
                    ? "textDark05"
                    : "text05";

  const Tag = as ?? "span";

  return (
    <Tag
      {...rest}
      className={cn(
        fonts[font],
        inverted ? colors.inverted[color] : colors[color],
        nowrap && "whitespace-nowrap",
        // NOTE: We want a small, horizontal padding applied to text components to visually
        // complement the white-space implicit with line-height. We apply to the before and after
        // pseudo-elements such that padding applied to the tag directly is additive making the
        // likelihood of 2px offsets with other text elements much lower.
        "before:content-[''] before:inline-block before:pl-[2px] after:content-[''] after:inline-block after:pr-[2px]",
        className
      )}
    >
      {children}
    </Tag>
  );
}
