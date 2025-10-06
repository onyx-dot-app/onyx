import * as React from "react";
import type { SVGProps } from "react";
const SvgOnyxOctagon = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <g clipPath="url(#clip0_586_578)">
      <path
        d="M4.5 2.50002L8 1.00002L11.5 2.50002M13.5 4.50002L15 8.00001L13.5 11.5M11.5 13.5L8 15L4.5 13.5M2.5 11.5L1 8L2.5 4.50002"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_586_578">
        <rect width={16} height={16} fill="white" />
      </clipPath>
    </defs>
  </svg>
);
export default SvgOnyxOctagon;
