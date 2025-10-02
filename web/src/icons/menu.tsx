import * as React from "react";
import type { SVGProps } from "react";
const SvgMenu = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 32 32"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M26.5 9H5.5M5.5 23H26.5M26.5 16H5.5"
      strokeWidth={2}
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgMenu;
