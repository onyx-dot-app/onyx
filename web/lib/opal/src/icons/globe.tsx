import * as React from "react";
import type { SVGProps } from "react";
const SvgGlobe = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <g clipPath="url(#clip0_16_2601)">
      <path
        d="M14.6667 7.99999C14.6667 11.6819 11.6819 14.6667 8.00001 14.6667M14.6667 7.99999C14.6667 4.3181 11.6819 1.33333 8.00001 1.33333M14.6667 7.99999H1.33334M8.00001 14.6667C4.31811 14.6667 1.33334 11.6819 1.33334 7.99999M8.00001 14.6667C9.66753 12.8411 10.6152 10.472 10.6667 7.99999C10.6152 5.52802 9.66753 3.1589 8.00001 1.33333M8.00001 14.6667C6.33249 12.8411 5.38484 10.472 5.33334 7.99999C5.38484 5.52802 6.33249 3.1589 8.00001 1.33333M1.33334 7.99999C1.33334 4.3181 4.31811 1.33333 8.00001 1.33333"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
    <defs>
      <clipPath id="clip0_16_2601">
        <rect width={16} height={16} fill="white" />
      </clipPath>
    </defs>
  </svg>
);
export default SvgGlobe;
