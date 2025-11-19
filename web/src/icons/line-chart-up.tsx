import * as React from "react";
import type { SVGProps } from "react";
const SvgLineChartUp = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M13 6.5L13 3M13 3H9.5M13 3L7.99999 8L6.49999 6.5L3 10M3 13H13"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgLineChartUp;
