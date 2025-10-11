import * as React from "react";
import type { SVGProps } from "react";
const SvgAddLines = (props: SVGProps<SVGSVGElement>) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 16 16"
    fill="none"
    {...props}
  >
    <path
      d="M14 6H2M14 3H2M6 12H2M11.5 9.5V12M11.5 12V14.5M11.5 12H9M11.5 12H14M8.5 9H2"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgAddLines;
