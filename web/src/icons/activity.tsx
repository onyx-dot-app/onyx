import * as React from "react";
import type { SVGProps } from "react";
const SvgActivity = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M14.6667 8H12L9.99999 14L5.99999 2L3.99999 8H1.33333"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgActivity;
