import * as React from "react";
import type { SVGProps } from "react";
const SvgSliders = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <g clipPath="url(#clip0_16_2627)">
      <path
        d="M2.66666 14V9.33333M2.66666 6.66667V2M7.99999 14V8M7.99999 5.33333V2M13.3333 14V10.6667M13.3333 8V2M0.666656 9.33333H4.66666M5.99999 5.33333H9.99999M11.3333 10.6667H15.3333"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_16_2627">
        <rect width={16} height={16} fill="white" />
      </clipPath>
    </defs>
  </svg>
);
export default SvgSliders;
