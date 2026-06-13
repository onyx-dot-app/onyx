import type { A11yProps, Handler, SizeToken, Slot } from "./primitives";

/** Visual-emphasis variants every platform's Button must support. */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

/**
 * Cross-platform API contract for a Button. Web and mobile each implement a
 * component whose props satisfy this contract, guaranteeing a consistent API
 * surface without sharing any rendering code.
 *
 * @typeParam TIcon - the platform's icon type (a React icon component on web,
 * an RN component on mobile). The contract never imports it directly.
 */
export interface ButtonContract<TIcon = unknown> extends A11yProps {
  label: string;
  variant?: ButtonVariant;
  size?: SizeToken;
  disabled?: boolean;
  loading?: boolean;
  /** Leading icon, platform-typed via `TIcon`. */
  leadingIcon?: Slot<TIcon>;
  /** Platform-neutral press handler (web maps to onClick, mobile to onPress). */
  onPress?: Handler;
}
