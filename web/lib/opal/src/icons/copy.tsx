import * as React from "react";
import type { SVGProps } from "react";
const SvgCopy = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <g clipPath="url(#clip0_16_2607)">
      <path
        d="M3.33333 9.99999H2.66666C2.31304 9.99999 1.9739 9.85952 1.72385 9.60947C1.4738 9.35942 1.33333 9.02028 1.33333 8.66666V2.66666C1.33333 2.31304 1.4738 1.9739 1.72385 1.72385C1.9739 1.4738 2.31304 1.33333 2.66666 1.33333H8.66666C9.02028 1.33333 9.35942 1.4738 9.60947 1.72385C9.85952 1.9739 9.99999 2.31304 9.99999 2.66666V3.33333M7.33333 5.99999H13.3333C14.0697 5.99999 14.6667 6.59695 14.6667 7.33333V13.3333C14.6667 14.0697 14.0697 14.6667 13.3333 14.6667H7.33333C6.59695 14.6667 5.99999 14.0697 5.99999 13.3333V7.33333C5.99999 6.59695 6.59695 5.99999 7.33333 5.99999Z"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_16_2607">
        <rect width={16} height={16} fill="white" />
      </clipPath>
    </defs>
  </svg>
);
export default SvgCopy;
