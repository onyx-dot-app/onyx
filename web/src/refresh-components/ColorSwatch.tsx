import "@/app/css/color-swatch.css";

/**
 * A small color swatch chip component that displays a visual preview of light or dark color modes.
 * Shows "Aa" text sample with appropriate background and text colors.
 *
 * @param light - If true, displays light mode swatch with light background and dark text
 * @param dark - If true, displays dark mode swatch with dark background and light text
 *
 * @example
 * <ColorSwatch light />
 * <ColorSwatch dark />
 */
export interface ColorSwatchProps {
  /** Display light mode variant */
  light?: boolean;
  /** Display dark mode variant */
  dark?: boolean;
}

export default function ColorSwatch({ light, dark }: ColorSwatchProps) {
  const mode = light ? "light" : dark ? "dark" : "light";

  return (
    <div className="color-swatch" data-state={mode}>
      <div className="rounded-full h-[0.3rem] w-[0.3rem] bg-action-link-05" />
      <span className="color-swatch__text">Aa</span>
    </div>
  );
}
