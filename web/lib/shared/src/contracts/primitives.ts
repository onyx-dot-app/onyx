/**
 * Platform-agnostic building blocks for component API contracts.
 *
 * These intentionally avoid importing React / React Native types. When a
 * contract needs a platform-specific value (an icon component, a rendered
 * node), it is expressed as a generic type parameter the consumer supplies
 * (web -> a React component, mobile -> an RN component). This is what keeps
 * the package free of any UI-framework dependency.
 */

/** A platform-supplied slot value (e.g. an icon or node); defaults to `unknown`. */
export type Slot<T = unknown> = T;

/** The lowest-common-denominator event handler: no args, no return. */
export type Handler = () => void;

/** Platform-neutral size scale used across contracts. */
export type SizeToken = "xs" | "sm" | "md" | "lg" | "xl";

/** Accessibility metadata each platform maps to its own native props. */
export interface A11yProps {
  /** Human-readable label for assistive technologies. */
  a11yLabel?: string;
  /** Marks the element as disabled for assistive technologies. */
  a11yDisabled?: boolean;
}
