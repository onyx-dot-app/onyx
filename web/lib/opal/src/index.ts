// Opal - A TSX component library for Onyx.
// This is the main entry point for the library.

import type { SVGProps } from "react";

// Version constant (must be defined for builds to work).
export const OPAL_VERSION = "0.1.0";

// Icon Props Interface
export interface IconProps extends SVGProps<SVGSVGElement> {
  className?: string;
  size?: number;
  title?: string;
  color?: string;
}
