import type { HTMLAttributes } from "react";

import {
  Text as OpalText,
  type TextFont,
  type TextColor,
} from "@opal/components";

// ---------------------------------------------------------------------------
// Compatibility wrapper
//
// Maps the legacy boolean-flag API to the new Opal Text string-enum API.
// New code should import Text from "@opal/components" directly.
// ---------------------------------------------------------------------------

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

const FONT_MAP: [keyof TextProps, TextFont][] = [
  ["headingH1", "heading-h1"],
  ["headingH2", "heading-h2"],
  ["headingH3", "heading-h3"],
  ["headingH3Muted", "heading-h3-muted"],
  ["mainContentBody", "main-content-body"],
  ["mainContentMuted", "main-content-muted"],
  ["mainContentEmphasis", "main-content-emphasis"],
  ["mainContentMono", "main-content-mono"],
  ["mainUiBody", "main-ui-body"],
  ["mainUiMuted", "main-ui-muted"],
  ["mainUiAction", "main-ui-action"],
  ["mainUiMono", "main-ui-mono"],
  ["secondaryBody", "secondary-body"],
  ["secondaryAction", "secondary-action"],
  ["secondaryMono", "secondary-mono"],
  ["figureSmallLabel", "figure-small-label"],
  ["figureSmallValue", "figure-small-value"],
  ["figureKeystroke", "figure-keystroke"],
];

const COLOR_MAP: [keyof TextProps, TextColor][] = [
  ["text01", "text-01"],
  ["text02", "text-02"],
  ["text03", "text-03"],
  ["text04", "text-04"],
  ["text05", "text-05"],
  ["textLight03", "text-light-03"],
  ["textLight05", "text-light-05"],
  ["textDark03", "text-dark-03"],
  ["textDark05", "text-dark-05"],
];

const INVERTED_COLOR_MAP: Record<TextColor, TextColor> = {
  "text-01": "text-inverted-01",
  "text-02": "text-inverted-02",
  "text-03": "text-inverted-03",
  "text-04": "text-inverted-04",
  "text-05": "text-inverted-05",
  "text-light-03": "text-light-03",
  "text-light-05": "text-light-05",
  "text-dark-03": "text-dark-03",
  "text-dark-05": "text-dark-05",
  "text-inverted-01": "text-inverted-01",
  "text-inverted-02": "text-inverted-02",
  "text-inverted-03": "text-inverted-03",
  "text-inverted-04": "text-inverted-04",
  "text-inverted-05": "text-inverted-05",
};

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
  const props: Record<string, boolean | undefined> = {
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
    text01,
    text02,
    text03,
    text04,
    text05,
    textLight03,
    textLight05,
    textDark03,
    textDark05,
  };

  const font: TextFont =
    FONT_MAP.find(([key]) => props[key])?.[1] ?? "main-ui-body";
  const baseColor: TextColor =
    COLOR_MAP.find(([key]) => props[key])?.[1] ?? "text-05";
  const color: TextColor = inverted ? INVERTED_COLOR_MAP[baseColor] : baseColor;

  return (
    <OpalText
      {...rest}
      font={font}
      color={color}
      as={as}
      nowrap={nowrap}
      preventMarkdown
      className={className}
    >
      {children}
    </OpalText>
  );
}
