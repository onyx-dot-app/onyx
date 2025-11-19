import * as React from "react";
import type { SVGProps } from "react";
const SvgBarChart = (props: SVGProps<SVGSVGElement>) => (
  <svg
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M12 13.3333V6.66666M8 13.3333V2.66666M4 13.3333V9.33332"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgBarChart;
