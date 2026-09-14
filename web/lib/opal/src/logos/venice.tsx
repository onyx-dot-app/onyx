import React from "react";
import type { IconProps } from "@opal/types";

// PLACEHOLDER MARK — replace with Venice's official logo before shipping.
// Geometric "V" standing in for the real asset so the provider card renders.
const SvgVenice = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M2.5 2.75h2.42l3.08 8.04 3.08-8.04h2.42L9.2 13.25H6.8L2.5 2.75Z"
      fill="var(--text-05)"
    />
  </svg>
);

export default SvgVenice;
