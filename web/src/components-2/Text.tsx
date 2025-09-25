const fonts = {
  // Heading
  headingH1: "font-heading-h1",
  headingH2: "font-heading-h2",
  headingH3: "font-heading-h3",
  headingH3Muted: "font-heading-h3-muted",

  // Main
  mainBody: "font-main-body",
  mainMuted: "font-main-muted",
  mainAction: "font-main-action",
  mainMono: "font-main-mono",

  // Secondary
  secondaryBody: "font-secondary-body",
  secondaryAction: "font-secondary-action",
  secondaryMono: "font-secondary-mono",

  // Figure
  figureSmallLabel: "font-figure-small-label",
  figureSmallValue: "font-figure-small-value",
  figureSmallKeystroke: "font-figure-small-keystroke",
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

export interface TextProps extends React.HTMLAttributes<HTMLElement> {
  nowrap?: boolean;

  // Fonts
  headingH1?: boolean;
  headingH2?: boolean;
  headingH3?: boolean;
  headingH3Muted?: boolean;
  mainBody?: boolean;
  mainMuted?: boolean;
  mainAction?: boolean;
  mainMono?: boolean;
  secondaryBody?: boolean;
  secondaryAction?: boolean;
  secondaryMono?: boolean;
  figureSmallLabel?: boolean;
  figureSmallValue?: boolean;
  figureSmallKeystroke?: boolean;

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
  mainBody,
  mainMuted,
  mainAction,
  mainMono,
  secondaryBody,
  secondaryAction,
  secondaryMono,
  figureSmallLabel,
  figureSmallValue,
  figureSmallKeystroke,
  text05,
  text04,
  text03,
  text02,
  text01,
  inverted,
  children,
  className,
}: TextProps) {
  const font = headingH1
    ? "headingH1"
    : headingH2
      ? "headingH2"
      : headingH3
        ? "headingH3"
        : headingH3Muted
          ? "headingH3Muted"
          : mainBody
            ? "mainBody"
            : mainMuted
              ? "mainMuted"
              : mainAction
                ? "mainAction"
                : mainMono
                  ? "mainMono"
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
                            : figureSmallKeystroke
                              ? "figureSmallKeystroke"
                              : "mainBody";

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
      className={`${fonts[font]} ${inverted ? colors.inverted[color] : colors[color]} ${nowrap && "whitespace-nowrap"} ${className}`}
    >
      {children}
    </p>
  );
}
